"""Track① usage-ledger queries — GET /usage/summary, GET /usage/turns (M2/M3).

Read-side of the ledger. Response naming follows DATA_MODEL §8.1:
``estimated_*`` prefixes, ``*_units`` fixed-point companions, ``basis``
declarations, ``partial`` honesty flags; never a bare ``cost``/``spend``/
``used`` key.

M3 pricing semantics (null ≠ 0 — DATA_MODEL §8.3):

* unpriced turns (``pricing_status='unknown_model'`` / counter resets) carry
  ``estimated_cost_units NULL`` — they surface as ``null`` in every payload
  and are counted under ``unpriced_turns``, never folded into a 0.00 sum;
* every money figure is per-currency (``*_by_currency`` lists) — multi-
  currency accounts are never merged (DR-12). The convenience top-level
  ``estimated_*`` fields name the PRIMARY bucket (largest sum; ties broken
  alphabetically) and are ``null`` when nothing was priced;
* ``basis`` declares the口径: ``whale_pricing`` | ``hermes_estimate`` |
  ``mixed`` | ``token_only`` (only unpriced turns present).
"""

from __future__ import annotations

import json
from typing import Any

from .clock import now_ms
from .ingest import local_day_key

TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")
SUMMARY_TOKEN_FIELDS = TOKEN_FIELDS + ("calls",)

DEFAULT_TURNS_LIMIT = 20
MAX_TURNS_LIMIT = 100

_DAY_MS = 86_400_000

#: daily_summary bucket for unpriced turns (see ingest.CURRENCY_PLACEHOLDER).
_UNPRICED_BUCKET = "none"


def _tokens_from_row(row: Any) -> dict[str, int]:
    calls = row["calls"] if "calls" in row.keys() else row["calls_delta"]
    return {
        "input": int(row["input_tokens"] or 0),
        "output": int(row["output_tokens"] or 0),
        "cache_read": int(row["cache_read_tokens"] or 0),
        "cache_write": int(row["cache_write_tokens"] or 0),
        "reasoning": int(row["reasoning_tokens"] or 0),
        "calls": int(calls or 0) if calls is not None else 0,
    }


def _cost_buckets(rows: list[Any]) -> list[dict[str, Any]]:
    """Group ``{currency, units, basis, priced, unpriced}`` rows per currency."""
    buckets: dict[str, dict[str, Any]] = {}
    for row in rows:
        currency = row["currency"]
        units = row["units"]
        if currency is None or units is None:
            continue
        bucket = buckets.setdefault(
            currency,
            {"currency": currency, "estimated_cost_units": 0, "bases": set(), "priced_turns": 0},
        )
        bucket["estimated_cost_units"] += int(units)
        bucket["bases"].add(row["basis"])
        bucket["priced_turns"] += 1
    out = []
    for currency in sorted(buckets):
        bucket = buckets[currency]
        bases = bucket.pop("bases")
        bucket["basis"] = bases.pop() if len(bases) == 1 else "mixed"
        out.append(bucket)
    return out


def _primary_bucket(buckets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Largest-sum bucket (tie → alphabetical currency) or None."""
    if not buckets:
        return None
    return max(buckets, key=lambda b: (b["estimated_cost_units"], b["currency"]))


def _turn_cost_rollup(conn, *, day: str | None = None, day_in: list[str] | None = None) -> list[dict[str, Any]]:
    """Per-currency cost sums over turn_cost (unpriced rows counted, not summed)."""
    if day is not None:
        where, params = "day = ?", [day]
    elif day_in:
        placeholders = ",".join("?" * len(day_in))
        where, params = f"day IN ({placeholders})", list(day_in)
    else:  # pragma: no cover - callers always pass a window
        where, params = "1=1", []
    rows = conn.execute(
        f"""
        SELECT currency, cost_basis,
               SUM(estimated_cost_units) AS units,
               COUNT(*) AS turns,
               SUM(CASE WHEN estimated_cost_units IS NULL THEN 1 ELSE 0 END) AS unpriced
        FROM turn_cost WHERE {where}
        GROUP BY currency, cost_basis
        """,
        params,
    ).fetchall()
    per_currency: dict[str, dict[str, Any]] = {}
    unpriced_total = 0
    for row in rows:
        if row["currency"] is None:
            unpriced_total += int(row["turns"] or 0)
            continue
        bucket = per_currency.setdefault(
            row["currency"],
            {"currency": row["currency"], "units": 0, "bases": set(), "priced_turns": 0, "unpriced_turns": 0},
        )
        if row["units"] is not None:
            bucket["units"] += int(row["units"])
            bucket["bases"].add(row["cost_basis"])
            bucket["priced_turns"] += int(row["turns"] or 0) - int(row["unpriced"] or 0)
        bucket["unpriced_turns"] += int(row["unpriced"] or 0)
    unpriced_none = per_currency.pop(_UNPRICED_BUCKET, None)
    if unpriced_none is not None:
        unpriced_total += unpriced_none["unpriced_turns"]
    result = []
    for currency in sorted(per_currency):
        bucket = per_currency[currency]
        bases = bucket.pop("bases")
        bucket["units"] = bucket["units"] or None
        bucket["basis"] = bases.pop() if len(bases) == 1 else "mixed"
        bucket["unpriced_turns"] += unpriced_total if not per_currency else 0
        result.append(bucket)
    # unpriced turns with a NULL currency belong to no currency bucket —
    # report them on the primary bucket only (single-bucket case below)
    if unpriced_total and result:
        for bucket in result:
            bucket["unpriced_turns"] += unpriced_total if len(result) == 1 else 0
    return result


def usage_summary(conn, *, days: int = 7, now: int | None = None) -> dict[str, Any]:
    """Today + trailing ``days`` rollup, per-model split, honesty flags."""
    ts = now_ms() if now is None else int(now)
    days = max(1, min(int(days), 366))
    today = local_day_key(ts)

    # ── today ──────────────────────────────────────────────────────────────
    row = conn.execute(
        """
        SELECT COUNT(*) AS turns,
               COALESCE(SUM(input_tokens), 0)       AS input_tokens,
               COALESCE(SUM(output_tokens), 0)      AS output_tokens,
               COALESCE(SUM(reasoning_tokens), 0)   AS reasoning_tokens,
               COALESCE(SUM(cache_read_tokens), 0)  AS cache_read_tokens,
               COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
               SUM(CASE WHEN calls_delta IS NOT NULL THEN calls_delta ELSE 0 END) AS calls
        FROM usage_event WHERE day = ?
        """,
        (today,),
    ).fetchone()
    tokens_today = _tokens_from_row(row)
    turns_today = int(row["turns"] or 0)

    today_buckets = _cost_buckets(
        [
            {"currency": r["currency"], "units": r["units"], "basis": r["basis"]}
            for r in conn.execute(
                """
                SELECT currency, cost_basis AS basis, SUM(estimated_cost_units) AS units
                FROM turn_cost WHERE day = ? AND estimated_cost_units IS NOT NULL
                GROUP BY currency, cost_basis
                """,
                (today,),
            ).fetchall()
        ]
    )
    unpriced_today = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM turn_cost WHERE day = ? AND estimated_cost_units IS NULL",
            (today,),
        ).fetchone()["n"]
    )
    for bucket in today_buckets:
        bucket["unpriced_turns"] = unpriced_today if len(today_buckets) <= 1 else 0
    primary = _primary_bucket(today_buckets)

    # ── trailing days (from daily_summary; absent days → empty entries) ────
    window = [local_day_key(ts - offset * _DAY_MS) for offset in range(days - 1, -1, -1)]
    placeholders = ",".join("?" * len(window))
    summary_rows = conn.execute(
        f"SELECT * FROM daily_summary WHERE track = 'usage' AND day IN ({placeholders}) ORDER BY scope",
        window,
    ).fetchall()
    by_day: dict[str, list[Any]] = {}
    for srow in summary_rows:
        by_day.setdefault(srow["day"], []).append(srow)

    estimated_days = []
    partial_days: list[str] = []
    for day in window:
        rows = by_day.get(day, [])
        tokens: dict[str, int] = {f: 0 for f in SUMMARY_TOKEN_FIELDS}
        partial = 0
        for srow in rows:
            partial = partial or int(srow["partial"] or 0)
            if srow["tokens_json"]:
                try:
                    data = json.loads(srow["tokens_json"])
                except ValueError:
                    data = {}
                total = data.get("total") if isinstance(data, dict) else None
                if isinstance(total, dict):
                    for f in SUMMARY_TOKEN_FIELDS:
                        tokens[f] += int(total.get(f) or 0)
        if partial:
            partial_days.append(day)

        day_buckets = _cost_buckets(
            [
                {"currency": srow["currency"], "units": srow["estimated_cost_units"], "basis": "turn_cost"}
                for srow in rows
                if srow["estimated_cost_units"] is not None
            ]
        )
        day_primary = _primary_bucket(day_buckets)
        day_unpriced = int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM turn_cost WHERE day = ? AND estimated_cost_units IS NULL",
                (day,),
            ).fetchone()["n"]
        )
        for bucket in day_buckets:
            bucket["unpriced_turns"] = day_unpriced if len(day_buckets) <= 1 else 0
        estimated_days.append(
            {
                "day": day,
                "estimated_cost_units": day_primary["estimated_cost_units"] if day_primary else None,
                "currency": day_primary["currency"] if day_primary else None,
                "basis": day_primary["basis"] if day_primary else ("token_only" if (rows or (day == today and turns_today > 0)) else None),
                "partial": partial,
                "tokens": tokens,
                "estimated_by_currency": day_buckets,
            }
        )

    # ── per-model split over the window ────────────────────────────────────
    per_model = []
    for mrow in conn.execute(
        f"""
        SELECT model, COUNT(*) AS turns,
               COALESCE(SUM(input_tokens), 0)       AS input_tokens,
               COALESCE(SUM(output_tokens), 0)      AS output_tokens,
               COALESCE(SUM(reasoning_tokens), 0)   AS reasoning_tokens,
               COALESCE(SUM(cache_read_tokens), 0)  AS cache_read_tokens,
               COALESCE(SUM(cache_write_tokens), 0) AS cache_write_tokens,
               SUM(CASE WHEN calls_delta IS NOT NULL THEN calls_delta ELSE 0 END) AS calls
        FROM usage_event WHERE day IN ({placeholders})
        GROUP BY model ORDER BY turns DESC, model ASC
        """,
        window,
    ).fetchall():
        entry = {"model": mrow["model"], "turns": int(mrow["turns"])}
        entry.update(_tokens_from_row(mrow))
        model_buckets = _cost_buckets(
            [
                {"currency": r["currency"], "units": r["units"], "basis": r["basis"]}
                for r in conn.execute(
                    """
                    SELECT currency, cost_basis AS basis, SUM(estimated_cost_units) AS units
                    FROM turn_cost WHERE model = ? AND day IN ({placeholders})
                      AND estimated_cost_units IS NOT NULL
                    GROUP BY currency, cost_basis
                    """.format(placeholders=placeholders),
                    (mrow["model"], *window),
                ).fetchall()
            ]
        )
        model_primary = _primary_bucket(model_buckets)
        model_unpriced = int(
            conn.execute(
                f"""
                SELECT COUNT(*) AS n FROM turn_cost
                WHERE model = ? AND day IN ({placeholders}) AND estimated_cost_units IS NULL
                """,
                (mrow["model"], *window),
            ).fetchone()["n"]
        )
        for bucket in model_buckets:
            bucket["unpriced_turns"] = model_unpriced if len(model_buckets) <= 1 else 0
        entry["estimated_cost_units"] = model_primary["estimated_cost_units"] if model_primary else None
        entry["currency"] = model_primary["currency"] if model_primary else None
        entry["estimated_by_currency"] = model_buckets
        per_model.append(entry)

    provisional_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM turn_cost WHERE status = 'provisional' AND day IN ({placeholders})",
        window,
    ).fetchone()

    return {
        "day": today,
        "estimated_today_units": primary["estimated_cost_units"] if primary else None,
        "estimated_today_currency": primary["currency"] if primary else None,
        "estimated_today_basis": primary["basis"] if primary else ("token_only" if turns_today > 0 else None),
        "estimated_today_by_currency": today_buckets,
        "turns_today": turns_today,
        "tokens_today": tokens_today,
        "estimated_days": estimated_days,
        "per_model": per_model,
        "partial_flags": {
            "partial_days": partial_days,
            "provisional_turns": int(provisional_row["n"] if provisional_row else 0),
        },
    }


def usage_turns(conn, *, limit: int = DEFAULT_TURNS_LIMIT, session_id: str | None = None) -> dict[str, Any]:
    """Most recent settled turns (bubble/detail view data source)."""
    limit = max(1, min(int(limit), MAX_TURNS_LIMIT))
    params: list[Any] = [limit]
    where = ""
    if session_id:
        where = "WHERE ue.session_id = ?"
        params = [session_id, limit]
    rows = conn.execute(
        f"""
        SELECT ue.dedup_key, ue.session_id, ue.turn_seq, ue.model, ue.day,
               ue.input_tokens, ue.output_tokens, ue.reasoning_tokens,
               ue.cache_read_tokens, ue.cache_write_tokens, ue.calls_delta,
               ue.received_at, ue.profile_name,
               tc.estimated_cost_units, tc.currency, tc.cost_basis, tc.pricing_status,
               tc.status, tc.settled_at
        FROM usage_event ue
        JOIN turn_cost tc ON tc.dedup_key = ue.dedup_key
        {where}
        ORDER BY ue.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    turns = []
    for row in rows:
        turns.append(
            {
                "dedup_key": row["dedup_key"],
                "session_id": row["session_id"],
                "turn_seq": int(row["turn_seq"]),
                "model": row["model"],
                "profile": row["profile_name"],
                "day": row["day"],
                "status": row["status"],
                "cost_basis": row["cost_basis"],
                "pricing_status": row["pricing_status"],
                # NULL = unpriced (unknown model / reset) — never rendered as 0
                "estimated_cost_units": row["estimated_cost_units"],
                "currency": row["currency"],
                "settled_at": int(row["settled_at"]),
                "received_at": int(row["received_at"]),
                "tokens": _tokens_from_row(row),
            }
        )
    return {"turns": turns, "count": len(turns), "limit": limit}
