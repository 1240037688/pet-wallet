"""Ingest — POST /ingest/turn: idempotent track① ledger writes (M2).

Replaces the M1 stub. Every settled turn (JS half only forwards
``message.complete`` turn-end snapshots — heartbeats never leave memory,
AGENTS.md §8) is recorded as exactly one ``usage_event`` + one ``turn_cost``
row, idempotent across duplicate / restart / reconnect / reload scenarios
(DATA_MODEL §3.4 scenario matrix).

Dedup design (DATA_MODEL §3.2, hardened here):

* ``dedup_key = sha256_hex(session_id | day | minute_bucket | turn_seq |
  source_event | model | input | output | cache_read | cache_write |
  reasoning | cost_basis | estimated_cost_units)[:40]`` — pinned by fixed
  test vectors (:data:`DEDUP_VECTOR`).
* The UNIQUE index alone cannot catch replays: ``turn_seq`` is assigned fresh
  per attempt, so a content lookup runs BEFORE turn_seq assignment — same
  (session, day, minute_bucket, source_event, model, five tokens, basis,
  units) → ``duplicate``, never a second row.
* A bounded fuzz window (:data:`REPLAY_WINDOW_MS`) additionally catches
  reconnect-replayed completions whose receive minute drifted (the gateway
  envelope carries no stable timestamp — AUDIT §3.1). Identical-content turns
  within the window are the R2-class accepted risk (undercount ≤ 1 turn).
* ``after_reconnect: true`` / ``replayed: true`` completions ALIGN the
  watermark only — no settlement (DATA_MODEL §3.4: "重连后首条 complete 只对齐
  watermark 不结算").

Counter reset (DATA_MODEL §3.3): snapshot < watermark on any counter → the
turn is recorded ``provisional`` / ``token_only`` with the post-reset absolute
values (new baseline 0 — never a negative delta), ``reset_count += 1``, and
the watermark aligns to the new snapshot. Known blind spot R1, honestly
marked rather than silently mis-recorded.

Cost fields (M2 boundary): M3 owns pricing. Every row is ``token_only`` with
``estimated_cost_units = 0`` (the DDL column is NOT NULL — 0 + basis is the
documented "no price computed yet" representation); ``cost_usd`` seen in the
snapshot is preserved verbatim inside ``cumulative_json`` so M3 can backfill.
``daily_summary.estimated_cost_units`` stays NULL (nullable column → honest
NULL, "null ≠ 0").

Money is 1e8 fixed-point; this module writes none yet (M3).

All timestamps: ``received_at`` comes from the payload (JS wall clock);
``day`` is the LOCAL-timezone date of ``received_at`` (DR-12);
``minute_bucket = received_at // 60000`` (epoch minutes are timezone-free).
The wall clock is injected via :mod:`whale_core.clock` (TEST_PLAN §2.3).
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .clock import now_ms
from .logging_setup import get_logger
from .security import assert_no_secrets_in_payload

log = get_logger("ingest")

SOURCE_EVENT = "message.complete"  # the only settlement entry point (DR-13)
MODEL_UNKNOWN = "unknown"
# M2 placeholder: no pricing yet (M3 owns cost/currency semantics).
CURRENCY_PLACEHOLDER = "none"
COST_BASIS_M2 = "token_only"
ESTIMATED_UNITS_M2 = 0

#: reconnect-replay fuzz window for the content lookup (see module docstring).
REPLAY_WINDOW_MS = 10 * 60_000

#: whitelist of usage fields accepted from the JS half (DATA_MODEL §8.4).
TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")
USAGE_WHITELIST = TOKEN_FIELDS + ("calls", "cost_usd", "context_used", "context_max", "context_percent")
TURN_STATUSES = ("complete", "error", "interrupted")

_MAX_SESSION_ID = 256
_MAX_MODEL = 256
_MAX_PROFILE = 128
_MAX_TURNS_PER_BATCH = 100
_MAX_RAW_JSON_BYTES = 16_384  # raw usage sub-object retention cap (defensive)


class IngestError(ValueError):
    """Invalid ingest payload → HTTP 400. Messages never echo payload values."""


# ---------------------------------------------------------------------------
# pure helpers (unit-test targets)
# ---------------------------------------------------------------------------

def local_day_key(received_at_ms: int) -> str:
    """Local-timezone day key ``YYYY-MM-DD`` of an epoch-ms timestamp (DR-12)."""
    lt = time.localtime(received_at_ms / 1000.0)
    return f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d}"


def minute_bucket(received_at_ms: int) -> int:
    """Epoch-minute index (timezone-free) — the dedup time window."""
    return int(received_at_ms) // 60_000


def compute_dedup_key(
    session_id: str,
    day: str,
    minute: int,
    turn_seq: int,
    source_event: str,
    model: str,
    toks: dict[str, int | None],
    cost_basis: str,
    estimated_cost_units: int,
) -> str:
    """DATA_MODEL §3.2 formula, sha256-hex truncated to 40 chars.

    Token fields participate in the fixed order input|output|cache_read|
    cache_write|reasoning; missing (None) snapshot fields contribute ``0``
    (the stored columns are NOT NULL DEFAULT 0 for deltas).
    """
    joined = "|".join(
        str(part)
        for part in (
            session_id,
            day,
            minute,
            turn_seq,
            source_event,
            model,
            toks.get("input") or 0,
            toks.get("output") or 0,
            toks.get("cache_read") or 0,
            toks.get("cache_write") or 0,
            toks.get("reasoning") or 0,
            cost_basis,
            estimated_cost_units,
        )
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:40]


def extract_usage(usage: Any) -> dict[str, int | float | None]:
    """Whitelist-extract the usage snapshot, NULL-aware (never fabricates 0).

    Token/call counts must be non-negative integers (bool excluded); context
    fields may be real numbers. Anything else degrades to None (R4).
    """
    out: dict[str, int | float | None] = {}
    if not isinstance(usage, dict):
        return {field: None for field in USAGE_WHITELIST}

    def _int(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int):
            return None
        return value if value >= 0 else None

    def _num(value: Any) -> int | float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return value

    for field in TOKEN_FIELDS:
        out[field] = _int(usage.get(field))
    out["calls"] = _int(usage.get("calls"))
    out["cost_usd"] = _num(usage.get("cost_usd"))
    for field in ("context_used", "context_max", "context_percent"):
        out[field] = _num(usage.get(field))
    return out


def _has_measurable_usage(usage: dict[str, Any]) -> bool:
    return any(usage.get(field) is not None for field in TOKEN_FIELDS) or usage.get("calls") is not None


# ---------------------------------------------------------------------------
# payload validation (400 on any violation; messages name fields, not values)
# ---------------------------------------------------------------------------

def validate_turn_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise IngestError("ingest payload must be a JSON object")
    try:
        assert_no_secrets_in_payload(payload)
    except ValueError as exc:
        raise IngestError(f"ingest payload rejected: {exc}") from None

    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id or len(session_id) > _MAX_SESSION_ID:
        raise IngestError("ingest payload invalid: session_id must be a non-empty string")

    received_at = payload.get("received_at")
    if isinstance(received_at, bool) or not isinstance(received_at, int) or received_at <= 0:
        raise IngestError("ingest payload invalid: received_at must be a positive epoch-ms integer")

    status = payload.get("status", "complete")
    if status not in TURN_STATUSES:
        raise IngestError("ingest payload invalid: status must be one of complete|error|interrupted")

    usage_raw = payload.get("usage")
    if not isinstance(usage_raw, dict):
        raise IngestError("ingest payload invalid: usage must be an object (use explicit nulls inside)")
    usage = extract_usage(usage_raw)

    model = payload.get("model")
    if model is None:
        model = MODEL_UNKNOWN
    if not isinstance(model, str) or not model or len(model) > _MAX_MODEL:
        raise IngestError("ingest payload invalid: model must be a non-empty string")

    profile = payload.get("profile")
    if profile is not None and (not isinstance(profile, str) or len(profile) > _MAX_PROFILE):
        raise IngestError("ingest payload invalid: profile must be a string")

    after_reconnect = payload.get("after_reconnect", False)
    replayed = payload.get("replayed", False)
    if not isinstance(after_reconnect, bool) or not isinstance(replayed, bool):
        raise IngestError("ingest payload invalid: after_reconnect/replayed must be booleans")

    usage_source = payload.get("usage_source")
    if usage_source is not None and usage_source not in ("complete", "heartbeat", "focused"):
        raise IngestError("ingest payload invalid: usage_source must be complete|heartbeat|focused")

    return {
        "session_id": session_id,
        "profile": profile,
        "model": model,
        "usage": usage,
        "usage_raw": usage_raw,
        "received_at": received_at,
        "status": status,
        "after_reconnect": after_reconnect,
        "replayed": replayed,
        "usage_source": usage_source,
    }


# ---------------------------------------------------------------------------
# watermark helpers
# ---------------------------------------------------------------------------

_WM_TOKEN_COLUMNS = {
    "input": "last_input",
    "output": "last_output",
    "cache_read": "last_cache_read",
    "cache_write": "last_cache_write",
    "reasoning": "last_reasoning",
}


def _get_watermark(conn, session_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM session_watermark WHERE session_id = ?", (session_id,)).fetchone()
    if row is None:
        return {
            "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "reasoning": 0,
            "last_calls": None, "reset_count": 0,
        }
    return {
        "input": row["last_input"],
        "output": row["last_output"],
        "cache_read": row["last_cache_read"],
        "cache_write": row["last_cache_write"],
        "reasoning": row["last_reasoning"],
        "last_calls": row["last_calls"],
        "reset_count": row["reset_count"],
    }


def _compute_delta(usage: dict[str, Any], wm: dict[str, Any]) -> tuple[dict[str, int | None], bool]:
    """Turn deltas = adjacent cumulative snapshot difference (DATA_MODEL §3.1).

    Returns (deltas, reset_detected). Missing snapshot fields contribute no
    delta (NULL-aware, R4); any counter BELOW its watermark signals a counter
    reset (gateway restart) — the delta becomes the post-reset absolute value
    (new baseline 0) and the turn is settled provisionally.
    """
    deltas: dict[str, int | None] = {}
    reset = False
    for field in TOKEN_FIELDS:
        snap = usage.get(field)
        if snap is None:
            deltas[field] = 0
            continue
        last = wm[field]
        if snap < last:
            reset = True
            deltas[field] = int(snap)
        else:
            deltas[field] = int(snap - last)

    calls = usage.get("calls")
    if calls is None:
        deltas["calls"] = None
    elif wm["last_calls"] is None:
        deltas["calls"] = int(calls)
    elif calls < wm["last_calls"]:
        reset = True
        deltas["calls"] = int(calls)
    else:
        deltas["calls"] = int(calls - wm["last_calls"])
    return deltas, reset


def _upsert_watermark(
    conn,
    session_id: str,
    usage: dict[str, Any],
    received_at: int,
    *,
    reset: bool,
) -> None:
    """Advance the watermark to the snapshot.

    Normal path: monotonic max per field (out-of-order replays can never drag
    it back). Reset path: align DOWN to the snapshot and count the reset
    (DATA_MODEL §3.3).
    """
    current = _get_watermark(conn, session_id)
    values: dict[str, int | None] = {}
    for field, column in _WM_TOKEN_COLUMNS.items():
        snap = usage.get(field)
        if snap is None:
            values[column] = current[field]
        elif reset:
            values[column] = int(snap)
        else:
            values[column] = max(current[field], int(snap))
    calls = usage.get("calls")
    if calls is None:
        values["last_calls"] = current["last_calls"]
    elif reset:
        values["last_calls"] = int(calls)
    elif current["last_calls"] is None:
        values["last_calls"] = int(calls)
    else:
        values["last_calls"] = max(current["last_calls"], int(calls))

    reset_count = current["reset_count"] + (1 if reset else 0)
    conn.execute(
        """
        INSERT INTO session_watermark(
            session_id, last_input, last_output, last_cache_read, last_cache_write,
            last_reasoning, last_calls, last_seen_at, reset_count)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            last_input=excluded.last_input, last_output=excluded.last_output,
            last_cache_read=excluded.last_cache_read, last_cache_write=excluded.last_cache_write,
            last_reasoning=excluded.last_reasoning, last_calls=excluded.last_calls,
            last_seen_at=excluded.last_seen_at, reset_count=excluded.reset_count
        """,
        (
            session_id,
            values["last_input"], values["last_output"], values["last_cache_read"],
            values["last_cache_write"], values["last_reasoning"], values["last_calls"],
            int(received_at), reset_count,
        ),
    )


def _touch_watermark(conn, session_id: str, received_at: int) -> None:
    """Keep last_seen_at fresh without touching counters."""
    conn.execute(
        """
        INSERT INTO session_watermark(
            session_id, last_input, last_output, last_cache_read, last_cache_write,
            last_reasoning, last_calls, last_seen_at, reset_count)
        VALUES (?, 0, 0, 0, 0, 0, NULL, ?, 0)
        ON CONFLICT(session_id) DO UPDATE SET last_seen_at=excluded.last_seen_at
        """,
        (session_id, int(received_at)),
    )


# ---------------------------------------------------------------------------
# duplicate lookup (the real dedup — see module docstring)
# ---------------------------------------------------------------------------

def _find_duplicate_exact(
    conn,
    session_id: str,
    cumulative_json: str,
    received_at: int,
) -> bool:
    """Byte-identical cumulative snapshot for the same session inside the same
    receive minute → duplicate.

    The lookup content is the REPLAY-STABLE session-cumulative snapshot (not
    the deltas): on a replay the watermark has already advanced to this
    snapshot, so re-computed deltas would be 0 and a delta-based lookup would
    miss the original row. ``turn_seq``/``minute_bucket`` stay in the dedup_key
    formula (pinned by vectors) — the UNIQUE index remains the race backstop.
    """
    row = conn.execute(
        """
        SELECT 1 FROM usage_event
        WHERE session_id = ? AND cumulative_json = ?
          AND received_at >= ? AND received_at < ?
        LIMIT 1
        """,
        (session_id, cumulative_json, (minute_bucket(received_at)) * 60_000, (minute_bucket(received_at) + 1) * 60_000),
    ).fetchone()
    return row is not None


def _find_duplicate_fuzzy(
    conn,
    session_id: str,
    cumulative_json: str,
    received_at: int,
) -> bool:
    """Same cumulative snapshot within :data:`REPLAY_WINDOW_MS` — reconnect
    replay guard for completions whose receive minute drifted."""
    row = conn.execute(
        """
        SELECT 1 FROM usage_event
        WHERE session_id = ? AND cumulative_json = ?
          AND received_at >= ? AND received_at <= ?
        LIMIT 1
        """,
        (session_id, cumulative_json, int(received_at) - REPLAY_WINDOW_MS, int(received_at) + REPLAY_WINDOW_MS),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# settlement
# ---------------------------------------------------------------------------

def _next_turn_seq(conn, session_id: str) -> int:
    row = conn.execute(
        "SELECT MAX(turn_seq) FROM usage_event WHERE session_id = ?", (session_id,)
    ).fetchone()
    return int(row[0] or 0) + 1


def _upsert_daily_summary(
    conn,
    profile: str | None,
    day: str,
    model: str,
    deltas: dict[str, Any],
    now: int,
) -> None:
    """Track① daily rollup (scope per DATA_MODEL §3.5; currency placeholder
    'none' until M3 pricing lands). Merges per-model token counters."""
    scope = f"usage:{profile or 'default'}:{CURRENCY_PLACEHOLDER}"
    fields = tuple(TOKEN_FIELDS) + ("calls",)

    def _zero() -> dict[str, int]:
        return {f: 0 for f in fields}

    row = conn.execute(
        "SELECT tokens_json FROM daily_summary WHERE scope = ? AND day = ? AND track = 'usage'",
        (scope, day),
    ).fetchone()
    if row and row["tokens_json"]:
        try:
            data = json.loads(row["tokens_json"])
        except ValueError:
            data = None
        if not isinstance(data, dict) or not isinstance(data.get("total"), dict) or not isinstance(data.get("models"), dict):
            data = None
    else:
        data = None
    data = data or {"total": _zero(), "models": {}}

    for f in fields:
        delta = deltas.get(f) or 0
        data["total"][f] = int(data["total"].get(f) or 0) + int(delta)
    mrow = data["models"].get(model)
    if not isinstance(mrow, dict):
        mrow = _zero()
    for f in fields:
        delta = deltas.get(f) or 0
        mrow[f] = int(mrow.get(f) or 0) + int(delta)
    data["models"][model] = mrow

    conn.execute(
        """
        INSERT INTO daily_summary(scope, day, track, currency, estimated_cost_units,
                                  tokens_json, partial, needs_review, updated_at)
        VALUES (?, ?, 'usage', ?, NULL, ?, 0, 0, ?)
        ON CONFLICT(scope, day, track) DO UPDATE SET
            tokens_json=excluded.tokens_json, updated_at=excluded.updated_at
        """,
        (scope, day, CURRENCY_PLACEHOLDER, json.dumps(data, ensure_ascii=False, sort_keys=True), int(now)),
    )


def ingest_turn(conn, payload: Any, *, now: int | None = None) -> dict[str, Any]:
    """Idempotently settle one turn payload. Returns the ingest response dict."""
    ts = clock_now(now)
    p = validate_turn_payload(payload)
    usage = p["usage"]
    session_id: str = p["session_id"]
    received_at: int = p["received_at"]
    day = local_day_key(received_at)
    minute = minute_bucket(received_at)

    # Alignment path: first completion after a reconnect / replayed completion
    # aligns the watermark WITHOUT settling (DATA_MODEL §3.4).
    if p["after_reconnect"] or p["replayed"]:
        if _has_measurable_usage(usage):
            _, reset = _compute_delta(usage, _get_watermark(conn, session_id))
            with conn:
                _upsert_watermark(conn, session_id, usage, received_at, reset=reset)
        else:
            with conn:
                _touch_watermark(conn, session_id, received_at)
        return {"status": "accepted", "accepted": 0, "duplicate": 0, "aligned": True}

    if not _has_measurable_usage(usage):
        # nothing measurable: keep session liveness, record nothing (no fabricated 0s)
        with conn:
            _touch_watermark(conn, session_id, received_at)
        return {"status": "accepted", "accepted": 0, "duplicate": 0, "aligned": False, "skipped": True}

    cost_basis = COST_BASIS_M2
    units = ESTIMATED_UNITS_M2

    # deltas are computed from the pre-settle watermark (pure function)
    wm = _get_watermark(conn, session_id)
    deltas, reset = _compute_delta(usage, wm)

    cumulative_json = json.dumps({k: usage.get(k) for k in USAGE_WHITELIST}, ensure_ascii=False, sort_keys=True)
    raw_payload_json = json.dumps(p["usage_raw"], ensure_ascii=False, sort_keys=True, default=str)
    if len(raw_payload_json) > _MAX_RAW_JSON_BYTES:
        raw_payload_json = cumulative_json  # defensive cap: keep the whitelist view

    if _find_duplicate_exact(conn, session_id, cumulative_json, received_at) or \
            _find_duplicate_fuzzy(conn, session_id, cumulative_json, received_at):
        # duplicate of an already-settled turn: never a second row; the
        # watermark already sits at/above this snapshot (monotonic max keeps it).
        with conn:
            _upsert_watermark(conn, session_id, usage, received_at, reset=reset)
        return {"status": "duplicate", "accepted": 0, "duplicate": 1, "aligned": False}

    with conn:  # single transaction per turn: rows are written together or not at all
        turn_seq = _next_turn_seq(conn, session_id)
        dedup_key = compute_dedup_key(
            session_id, day, minute, turn_seq, SOURCE_EVENT, p["model"],
            deltas, cost_basis, units,
        )
        status = "provisional" if (reset or p["status"] != "complete") else "final"
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO usage_event(
                dedup_key, session_id, turn_seq, source_event, model,
                input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, cache_write_tokens,
                calls_delta, context_used, context_max, context_percent,
                cumulative_json, raw_payload_json, profile_name, day, received_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dedup_key, session_id, turn_seq, SOURCE_EVENT, p["model"],
                int(deltas.get("input") or 0), int(deltas.get("output") or 0),
                int(deltas.get("reasoning") or 0), int(deltas.get("cache_read") or 0),
                int(deltas.get("cache_write") or 0),
                deltas.get("calls"),
                usage.get("context_used"), usage.get("context_max"), usage.get("context_percent"),
                cumulative_json, raw_payload_json, p["profile"], day, int(received_at),
            ),
        )
        inserted = cur.rowcount
        conn.execute(
            """
            INSERT OR IGNORE INTO turn_cost(
                dedup_key, session_id, turn_seq, model, estimated_cost_units,
                currency, cost_basis, pricing_snapshot_json, status, day, settled_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            """,
            (
                dedup_key, session_id, turn_seq, p["model"], int(units),
                CURRENCY_PLACEHOLDER, cost_basis, status, day, int(ts),
            ),
        )
        _upsert_watermark(conn, session_id, usage, received_at, reset=reset)
        _upsert_daily_summary(conn, p["profile"], day, p["model"], deltas, ts)

    if not inserted:
        # lost a race against a concurrent identical write — report honestly
        return {"status": "duplicate", "accepted": 0, "duplicate": 1, "aligned": False}
    return {"status": "accepted", "accepted": 1, "duplicate": 0, "aligned": False}


def ingest_batch(conn, payloads: list[Any], *, now: int | None = None) -> dict[str, Any]:
    """Settle a batch; each turn commits in its own transaction (error isolation)."""
    if not isinstance(payloads, list):
        raise IngestError("ingest payload invalid: turns must be a list")
    if not (1 <= len(payloads) <= _MAX_TURNS_PER_BATCH):
        raise IngestError(f"ingest payload invalid: turns must contain 1..{_MAX_TURNS_PER_BATCH} items")
    accepted = 0
    duplicate = 0
    aligned = False
    skipped = 0
    for payload in payloads:
        result = ingest_turn(conn, payload, now=now)
        accepted += result["accepted"]
        duplicate += result["duplicate"]
        aligned = aligned or bool(result.get("aligned"))
        skipped += 1 if result.get("skipped") else 0
    response: dict[str, Any] = {
        "status": "accepted" if accepted > 0 else "duplicate",
        "accepted": accepted,
        "duplicate": duplicate,
    }
    if aligned:
        response["aligned"] = True
    if skipped:
        response["skipped"] = skipped
    return response


def clock_now(now: int | None) -> int:
    return now_ms() if now is None else int(now)
