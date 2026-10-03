"""Track① usage-ledger queries — GET /usage/summary, GET /usage/turns (M2).

Read-side of the ledger. Response naming follows DATA_MODEL §8.1:
``estimated_*`` prefixes, ``*_units`` fixed-point companions, ``basis``
declarations, ``partial`` honesty flags; never a bare ``cost``/``spend``/
``used`` key. Cost figures stay NULL until M3 pricing lands (null ≠ 0 —
DATA_MODEL §8.3: "no price computed yet" must not display as 0.00).
"""

from __future__ import annotations

import json
from typing import Any

from .clock import now_ms
from .ingest import CURRENCY_PLACEHOLDER, local_day_key

TOKEN_FIELDS = ("input", "output", "cache_read", "cache_write", "reasoning")
SUMMARY_TOKEN_FIELDS = TOKEN_FIELDS + ("calls",)

DEFAULT_TURNS_LIMIT = 20
MAX_TURNS_LIMIT = 100

_DAY_MS = 86_400_000


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

    # M2: no pricing → estimated stays NULL even when turns exist (null ≠ 0).
    # basis names the honest reason ('token_only'); None when no turns at all.
    estimated_today_units: int | None = None
    estimated_today_basis: str | None = "token_only" if turns_today > 0 else None

    # ── trailing days (from daily_summary; absent days → empty entries) ────
    window = [local_day_key(ts - offset * _DAY_MS) for offset in range(days - 1, -1, -1)]
    placeholders = ",".join("?" * len(window))
    summary_rows = {
        r["day"]: r
        for r in conn.execute(
            f"SELECT * FROM daily_summary WHERE track = 'usage' AND day IN ({placeholders})",
            window,
        ).fetchall()
    }
    estimated_days = []
    partial_days: list[str] = []
    for day in window:
        srow = summary_rows.get(day)
        tokens: dict[str, int] = {f: 0 for f in SUMMARY_TOKEN_FIELDS}
        partial = 0
        if srow is not None and srow["tokens_json"]:
            try:
                data = json.loads(srow["tokens_json"])
            except ValueError:
                data = {}
            total = data.get("total") if isinstance(data, dict) else None
            if isinstance(total, dict):
                tokens = {f: int(total.get(f) or 0) for f in SUMMARY_TOKEN_FIELDS}
            partial = int(srow["partial"] or 0)
        if partial:
            partial_days.append(day)
        basis = "token_only" if (srow is not None or (day == today and turns_today > 0)) else None
        estimated_days.append(
            {
                "day": day,
                "estimated_cost_units": None,  # M3 pricing lands here
                "currency": None,
                "basis": basis,
                "partial": partial,
                "tokens": tokens,
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
        per_model.append(entry)

    provisional_row = conn.execute(
        f"SELECT COUNT(*) AS n FROM turn_cost WHERE status = 'provisional' AND day IN ({placeholders})",
        window,
    ).fetchone()

    return {
        "day": today,
        "estimated_today_units": estimated_today_units,
        "estimated_today_currency": None,
        "estimated_today_basis": estimated_today_basis,
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
               tc.estimated_cost_units, tc.currency, tc.cost_basis, tc.status, tc.settled_at
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
                "estimated_cost_units": row["estimated_cost_units"],
                "currency": None if row["currency"] == CURRENCY_PLACEHOLDER else row["currency"],
                "settled_at": int(row["settled_at"]),
                "received_at": int(row["received_at"]),
                "tokens": _tokens_from_row(row),
            }
        )
    return {"turns": turns, "count": len(turns), "limit": limit}
