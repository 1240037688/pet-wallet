"""Track② balance ledger — snapshots, differencing, adjustments, state machine (M4).

Hard rules (AGENTS.md §8 / DATA_MODEL §2.5-§2.7, §6):

* API failure ≠ 0 — errors produce ``error``/``stale``/``unknown`` states and
  never write an amount; only an ``ok`` observation with a genuine zero
  balance yields the ``zero`` state.
* Differencing ([DSH] A1 ``observeBalance``): a falling balance accumulates
  ``observed_spend_units``; a rising balance accumulates ``credit_units``
  (top-ups/grants) and **never cancels spend**. Reconciliation is the explicit
  ``apply_adjustment`` closure (implied usage formula + revision-409), not a
  silent rewrite.
* Observation gaps: ``gap_seconds > GAP_PARTIAL_THRESHOLD_S`` (10 min, [DSH]
  partialDay) marks the materialised day ``partial=1`` — offline periods are
  flagged, not silently dropped.
* Scopes: every snapshot is booked under ``credential_fingerprint`` —
  switching/deleting a key starts a fresh book; books are never merged.
* Money: 1e8 fixed point; ``granted``/``topped_up`` absent = NULL, never 0.

Persisted error state lives in ``whale_meta`` (``balance.last_error.<pid>``)
as ``{kind, http_status, at}`` — kinds only, never raw exception text.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from . import config, pricing
from .clock import now_ms
from .ingest import local_day_key
from .logging_setup import get_logger
from .providers import base as provider_base
from .providers import gateway, registry
from .security import assert_no_secrets_in_payload

log = get_logger("balance_ledger")

DEFAULT_PROVIDER_ID = "deepseek"
FRESH_TTL_MS = 120_000  # display staleness for the last known balance
GAP_PARTIAL_THRESHOLD_S = 600  # [DSH] partialDay: >10 min without observation

_META_ERROR_PREFIX = "balance.last_error."


class AdjustmentConflict(Exception):
    """Revision mismatch on a correction write → HTTP 409 at the API layer."""

    def __init__(self, expected: str | None, got: str | None) -> None:
        super().__init__("balance adjustment revision mismatch")
        self.expected = expected
        self.got = got


# ---------------------------------------------------------------------------
# snapshot ingestion + differencing
# ---------------------------------------------------------------------------

def record_snapshot(
    conn,
    *,
    provider_id: str,
    scope: str,
    currency: str,
    observed_balance_units: int,
    granted_units: int | None,
    topped_up_units: int | None,
    raw: dict[str, Any],
    fetched_at: int,
    fetch_state: str = "ok",
) -> dict[str, Any]:
    """Insert one ok/stale_cache observation and difference it into the day row.

    Returns ``{inserted, day, spend_delta_units, credit_delta_units,
    gap_seconds, partial}``. Duplicate (same balance, same ms — UNIQUE hit) or
    non-monotonic (``fetched_at <= last``) observations are ignored: they must
    never double-book a diff.
    """
    assert_no_secrets_in_payload(raw)
    _ensure_provider_row(conn, provider_id, scope, currency)
    day = local_day_key(fetched_at)
    prev = conn.execute(
        """
        SELECT observed_balance_units, fetched_at FROM balance_snapshot
        WHERE provider_id = ? AND scope = ? AND currency = ?
        ORDER BY fetched_at DESC LIMIT 1
        """,
        (provider_id, scope, currency),
    ).fetchone()

    inserted = conn.execute(
        """
        INSERT OR IGNORE INTO balance_snapshot
          (provider_id, scope, currency, observed_balance_units, granted_units,
           topped_up_units, raw_response_json, fetched_at, fetch_state)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            provider_id, scope, currency, observed_balance_units, granted_units,
            topped_up_units, json.dumps(raw, ensure_ascii=False, sort_keys=True),
            fetched_at, fetch_state,
        ),
    ).rowcount

    spend_delta = credit_delta = 0
    gap_seconds: int | None = None
    partial = 0
    if prev is not None and inserted:
        delta = observed_balance_units - int(prev["observed_balance_units"])
        if delta < 0:
            spend_delta = -delta  # consumption
        elif delta > 0:
            credit_delta = delta  # top-up / grant — never cancels spend
        gap_seconds = max(0, (fetched_at - int(prev["fetched_at"])) // 1000)
        partial = 1 if gap_seconds > GAP_PARTIAL_THRESHOLD_S else 0
        _materialise_day(
            conn, scope=scope, day=day, currency=currency,
            opening_units=int(prev["observed_balance_units"]),
            last_units=observed_balance_units,
            spend_delta=spend_delta, credit_delta=credit_delta,
            gap_seconds=gap_seconds, partial=partial,
            observed_from=int(prev["fetched_at"]), observed_to=fetched_at,
        )
    conn.commit()
    return {
        "inserted": bool(inserted),
        "day": day,
        "spend_delta_units": spend_delta,
        "credit_delta_units": credit_delta,
        "gap_seconds": gap_seconds,
        "partial": bool(partial),
    }


def _ensure_provider_row(conn, provider_id: str, scope: str, currency: str) -> None:
    """FK target for balance_snapshot: register the provider instance once.

    The row carries the credential FINGERPRINT (never the key) and marks the
    template kind; idempotent across snapshots.
    """
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO provider
              (id, template_key, name, kind, currency, credential_ref,
               credential_fingerprint, enabled, created_at, updated_at)
            VALUES (?, ?, ?, 'balance', ?, ?, ?, 1, ?, ?)
            """,
            (provider_id, provider_id, provider_id, currency, provider_id, scope,
             now_ms(), now_ms()),
        )
    except Exception as exc:  # noqa: BLE001 - registration must not block booking
        log.warning("provider row registration skipped for %s: %s", provider_id, type(exc).__name__)


def _materialise_day(
    conn, *, scope: str, day: str, currency: str, opening_units: int,
    last_units: int, spend_delta: int, credit_delta: int,
    gap_seconds: int | None, partial: int, observed_from: int, observed_to: int,
) -> None:
    """Upsert the ``daily_summary`` track='balance' row for one observation."""
    row = conn.execute(
        "SELECT observed_from, gap_seconds, partial FROM daily_summary WHERE scope=? AND day=? AND track='balance'",
        (scope, day),
    ).fetchone()
    from_from = min(observed_from, observed_to)
    from_to = max(observed_from, observed_to)
    if row is None:
        conn.execute(
            """
            INSERT INTO daily_summary
              (scope, day, track, currency, opening_units, last_units,
               observed_spend_units, credit_units, partial, observed_from,
               observed_to, gap_seconds, updated_at)
            VALUES (?, ?, 'balance', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (scope, day, currency, opening_units, last_units, spend_delta,
             credit_delta, partial, from_from, from_to, gap_seconds, now_ms()),
        )
        return
    merged_gap = row["gap_seconds"]
    if gap_seconds is not None:
        merged_gap = gap_seconds if merged_gap is None else max(int(merged_gap), gap_seconds)
    conn.execute(
        """
        UPDATE daily_summary SET last_units=?, currency=?,
          observed_spend_units = COALESCE(observed_spend_units, 0) + ?,
          credit_units = COALESCE(credit_units, 0) + ?,
          partial = MAX(partial, ?), observed_from = MIN(COALESCE(observed_from, ?), ?),
          observed_to = MAX(COALESCE(observed_to, ?), ?), gap_seconds = ?, updated_at = ?
        WHERE scope=? AND day=? AND track='balance'
        """,
        (last_units, currency, spend_delta, credit_delta, partial,
         from_from, from_from, from_to, from_to, merged_gap, now_ms(),
         scope, day),
    )


# ---------------------------------------------------------------------------
# explicit correction (the reconciliation closure; revision-409)
# ---------------------------------------------------------------------------

def apply_adjustment(
    conn, *, scope: str, day: str, currency: str, credits_units: int,
    other_debits_units: int = 0, revision: str | None = None, now: int | None = None,
) -> dict[str, Any]:
    """Recompute the day's implied usage: ``opening + credits − other debits − last``.

    Requires an existing balance-tracked day row (no opening → no correction).
    Optimistic concurrency: a non-matching ``revision`` raises
    :class:`AdjustmentConflict` (API maps to 409).
    """
    row = conn.execute(
        "SELECT opening_units, last_units, observed_spend_units, revision FROM daily_summary "
        "WHERE scope=? AND day=? AND track='balance'",
        (scope, day),
    ).fetchone()
    if row is None:
        raise LookupError(f"no balance observations recorded for {day}")
    if (row["revision"] or None) != (revision or None):
        raise AdjustmentConflict(row["revision"], revision)
    opening = row["opening_units"]
    last = row["last_units"]
    if opening is None or last is None:
        raise LookupError("day row lacks opening/last balances; cannot correct")
    implied = max(0, int(opening) + int(credits_units) - int(other_debits_units) - int(last))
    new_revision = uuid.uuid4().hex
    log_entry = json.dumps(
        {"at": now or now_ms(), "implied_usage_units": implied,
         "credits_units": credits_units, "other_debits_units": other_debits_units},
        ensure_ascii=False, sort_keys=True,
    )
    # audit trail lives in balance_adjustment (one row per correction);
    # daily_summary only carries the outcome + revision (optimistic-concurrency token)
    conn.execute(
        """
        UPDATE daily_summary SET observed_spend_units=?, revision=?, needs_review=0
        WHERE scope=? AND day=? AND track='balance'
        """,
        (implied, new_revision, scope, day),
    )
    conn.execute(
        """
        INSERT INTO balance_adjustment
          (scope, currency, day, credits_units, other_debits_units,
           implied_usage_units, revision, correction_log_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (scope, currency, day, credits_units, other_debits_units, implied,
         new_revision, log_entry, now or now_ms()),
    )
    conn.commit()
    return {"day": day, "adjustment_implied_usage_units": implied, "revision": new_revision}


# ---------------------------------------------------------------------------
# error state (whale_meta) + five-state machine view
# ---------------------------------------------------------------------------

def _store_error(conn, provider_id: str, exc: Exception, at: int) -> None:
    payload = json.dumps(
        {"kind": getattr(exc, "kind", "provider_error"),
         "http_status": getattr(exc, "http_status", None), "at": at},
        ensure_ascii=False, sort_keys=True,
    )
    conn.execute(
        "INSERT INTO whale_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_META_ERROR_PREFIX + provider_id, payload),
    )
    conn.commit()


def _clear_error(conn, provider_id: str) -> None:
    conn.execute("DELETE FROM whale_meta WHERE key = ?", (_META_ERROR_PREFIX + provider_id,))
    conn.commit()


def _load_error(conn, provider_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value FROM whale_meta WHERE key = ?", (_META_ERROR_PREFIX + provider_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["value"])
    except ValueError:
        return None


def refresh_balance(conn, *, provider_id: str = DEFAULT_PROVIDER_ID, transport: Any = None) -> dict[str, Any]:
    """Fetch + record one observation; on failure keep the last known balance.

    Never raises for provider-level failures — the returned state carries the
    error kind instead (REST callers get a 200 with ``state: 'error'``;
    the API failure is data, not a crash).
    """
    at = now_ms()
    cred = gateway.resolve_credential(provider_id)
    if cred is None:
        log.info("balance refresh skipped: no credential for %s", provider_id)
        state = balance_state(conn, provider_id=provider_id)
        state["refresh_skipped"] = "not_configured"
        return state
    try:
        provider = registry.get_provider(provider_id)
        snapshot = provider.fetch_balance(cred, transport=transport)
    except provider_base.ProviderError as exc:
        log.warning("balance refresh failed for %s: kind=%s status=%s",
                    provider_id, exc.kind, exc.http_status)
        _store_error(conn, provider_id, exc, at)
        return balance_state(conn, provider_id=provider_id)
    record_snapshot(conn, **snapshot, fetch_state="ok")
    _clear_error(conn, provider_id)
    return balance_state(conn, provider_id=provider_id)


def balance_state(conn, *, provider_id: str = DEFAULT_PROVIDER_ID, now: int | None = None) -> dict[str, Any]:
    """Five-state view: unknown / zero / error / stale / ok (DATA_MODEL §6).

    ``observed_balance_units`` is the LAST KNOWN balance even in error/stale
    states; it is ``None`` only when nothing was ever observed.
    """
    ts = now_ms() if now is None else int(now)
    cred_status = gateway.credential_status(provider_id)
    payload: dict[str, Any] = {
        "provider_id": provider_id,
        "credential": cred_status,
        "state": "unknown",
        "observed_balance_units": None,
        "granted_units": None,
        "topped_up_units": None,
        "currency": None,
        "fingerprint": None,
        "fetched_at": None,
        "stale": False,
        "error": None,
    }
    if not cred_status.get("configured"):
        payload["reason"] = "not_configured"
        return payload
    payload["fingerprint"] = cred_status.get("fingerprint")

    last = conn.execute(
        """
        SELECT scope, currency, observed_balance_units, granted_units,
               topped_up_units, fetched_at FROM balance_snapshot
        WHERE provider_id = ? ORDER BY fetched_at DESC LIMIT 1
        """,
        (provider_id,),
    ).fetchone()
    error = _load_error(conn, provider_id)

    if last is None:
        if error is not None:
            payload["state"] = "error"
            payload["error"] = error
        return payload

    fetched_at = int(last["fetched_at"])
    stale = (ts - fetched_at) > FRESH_TTL_MS
    payload.update(
        observed_balance_units=int(last["observed_balance_units"]),
        granted_units=last["granted_units"],
        topped_up_units=last["topped_up_units"],
        currency=last["currency"],
        fingerprint=last["scope"],
        fetched_at=fetched_at,
        stale=stale,
    )
    if stale:
        payload["state"] = "stale"
    elif error is not None and int(error.get("at", 0)) > fetched_at:
        payload["state"] = "error"
        payload["error"] = error
    elif payload["observed_balance_units"] == 0:
        payload["state"] = "zero"
    else:
        payload["state"] = "ok"
    return payload


# ---------------------------------------------------------------------------
# day aggregation (REST /balance/summary)
# ---------------------------------------------------------------------------

def balance_summary(conn, *, days: int = 7, now: int | None = None) -> dict[str, Any]:
    """Trailing-``days`` track② rollup across scopes (merged per day+currency)."""
    ts = now_ms() if now is None else int(now)
    days = max(1, min(int(days), 366))
    today = local_day_key(ts)
    cutoff = _shift_day(today, -(days - 1))
    rows = conn.execute(
        """
        SELECT day, currency,
               SUM(COALESCE(observed_spend_units, 0)) AS observed_spend_units,
               SUM(COALESCE(credit_units, 0))         AS credit_units,
               MAX(partial) AS partial, MAX(needs_review) AS needs_review,
               SUM(COALESCE(gap_seconds, 0)) AS gap_seconds, revision
        FROM daily_summary WHERE track = 'balance' AND day >= ?
        GROUP BY day, currency ORDER BY day DESC
        """,
        (cutoff,),
    ).fetchall()
    return {
        "days": [
            {
                "day": r["day"],
                "currency": r["currency"],
                "observed_spend_units": int(r["observed_spend_units"]),
                "credit_units": int(r["credit_units"]),
                "partial": bool(r["partial"]),
                "needs_review": bool(r["needs_review"]),
                "gap_seconds": int(r["gap_seconds"]),
                "revision": r["revision"],
            }
            for r in rows
        ]
    }


def _shift_day(day: str, delta: int) -> str:
    """Local-day arithmetic for the summary window (calendar-day based)."""
    import datetime as _dt

    d = _dt.date.fromisoformat(day) + _dt.timedelta(days=delta)
    return d.isoformat()
