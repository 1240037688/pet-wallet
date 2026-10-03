"""Rules — budget / low-balance / per-turn-cost reminder evaluation (M8).

Pure evaluation entry points, called from two minimal hooks (IMPLEMENTATION_PLAN
M8 task 1):

* ``ingest.py`` settlement-success tail → :func:`evaluate_turn_cost` +
  :func:`evaluate_daily_budget`;
* ``balance_ledger.record_snapshot`` tail → :func:`evaluate_balance_low`.

Both hooks wrap the calls in ``try/except`` — a rules failure must never touch
the booking chain's return value or transaction semantics (WP-2 hard rule).

Dedup keys are persisted in the ``notification`` table (DR-14: restart/replay
never re-rings; DATA_MODEL §2.10):

* ``balance_low:{scope}:{day}`` — at most one low-balance ring per scope per
  local day; recovery (≥ threshold) auto-dismisses the standing notification
  (display-level hysteresis); the next local day re-arms the key (跨日重置).
* ``budget:{scope}:{day}`` — one budget ring per over-budget scope per day.
* ``turn:{turn_dedup_key}`` — inherits the settlement idempotency: a replayed
  turn settles once → rings once.

Configuration (config.json, deep-merged over ``config.DEFAULTS``):
``thresholds.balance_low`` / ``thresholds.daily_budget`` / ``thresholds.turn_cost_min``
are decimal currency amounts; ``None`` (null) disables that rule — null ≠ 0
semantics (DATA_MODEL §8.3). Toggles live under ``reminders``. Money is
converted through :func:`pricing.to_units` (1e8 fixed point) at evaluation
time; a misconfigured non-numeric threshold degrades to "rule off" (logged),
never to a spurious ring.

Multi-currency honesty (DR-12): the daily budget compares per
``daily_summary`` scope row (each currency is its own ledger) — currencies are
never merged to reach a budget.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import config, notifications, pricing
from .clock import now_ms
from .ingest import local_day_key
from .logging_setup import get_logger

log = get_logger("rules")

DAY_SECONDS_MS = 86_400_000  # documentation only — day keys come from local_day_key


def _cfg(home: str | None = None) -> dict[str, Any]:
    return config.load_config(home)


def _enabled(reminders: dict[str, Any], key: str, default: bool = True) -> bool:
    value = reminders.get(key, default)
    return value is not False and bool(value)


def _threshold_units(raw: Any, *, label: str) -> int | None:
    """Decimal threshold → 1e8 units; None = rule off; bad value = rule off."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        log.warning("threshold %s is a boolean — treating as unset", label)
        return None
    try:
        units = pricing.to_units(raw)
    except (pricing.PricingError, OverflowError) as exc:
        log.warning("threshold %s invalid (%s) — treating as unset", label, type(exc).__name__)
        return None
    return units if units >= 0 else None


# ---------------------------------------------------------------------------
# balance low (track② — evaluated after every successful snapshot)
# ---------------------------------------------------------------------------

def evaluate_balance_low(
    conn: sqlite3.Connection,
    *,
    scope: str,
    currency: str | None,
    observed_balance_units: int,
    now: int | None = None,
    home: str | None = None,
) -> dict[str, Any]:
    """Low-balance edge: fire below threshold; auto-dismiss on recovery.

    ``observed_balance_units`` is a fresh ``ok`` observation (record_snapshot
    only evaluates after a successful fetch — error/stale states never reach a
    money comparison, DATA_MODEL §6 hard rule 1). Dedup:
    ``balance_low:{scope}:{day}`` — persistent, so a restart/replay of the same
    observation cannot re-ring (DR-14); the day key re-arms it daily.
    """
    ts = now_ms() if now is None else int(now)
    cfg = _cfg(home)
    reminders = cfg.get("reminders") or {}
    if not _enabled(reminders, "balance_low_enabled"):
        return {"action": "skipped", "reason": "disabled"}
    threshold_units = _threshold_units((cfg.get("thresholds") or {}).get("balance_low"), label="balance_low")
    if threshold_units is None:
        return {"action": "skipped", "reason": "threshold_unset"}

    day = local_day_key(ts)
    dedup_key = f"balance_low:{scope}:{day}"
    balance = int(observed_balance_units)
    if balance < threshold_units:
        status = notifications.fire(
            conn,
            kind="balance_low",
            rank=notifications.RANK_BALANCE_LOW,
            dedup_key=dedup_key,
            payload={
                "observed_balance_units": balance,
                "balance_low_threshold_units": threshold_units,
                "currency": currency,
                "day": day,
            },
            ttl_ms=0,  # standing alert: persistent until recovery dismisses it
            now=ts,
        )
        return {"action": status, "dedup_key": dedup_key, "day": day}

    # Recovery edge (≥ threshold): close the standing bubble. The dedup row
    # itself persists — within the same day a re-dip stays silent (DR-14
    # outranks re-ringing); the next local day re-arms the key.
    dismissed = notifications.dismiss_active(
        conn, kind="balance_low", dedup_prefix=f"balance_low:{scope}:", now=ts,
    )
    if dismissed:
        return {"action": "cleared", "dedup_key": dedup_key, "dismissed": dismissed}
    return {"action": "idle", "dedup_key": dedup_key}


# ---------------------------------------------------------------------------
# daily budget (track① — evaluated after every successful settlement)
# ---------------------------------------------------------------------------

def evaluate_daily_budget(
    conn: sqlite3.Connection,
    *,
    now: int | None = None,
    home: str | None = None,
) -> dict[str, Any]:
    """Fire ``budget`` once per over-budget usage scope for the local day.

    Each ``daily_summary`` track='usage' row (scope ``usage:<profile>:<currency>``,
    i.e. per currency) is compared independently — estimated costs of different
    currencies are never summed (DR-12). Dedup: ``budget:{scope}:{day}``.
    """
    ts = now_ms() if now is None else int(now)
    cfg = _cfg(home)
    reminders = cfg.get("reminders") or {}
    if not _enabled(reminders, "budget_enabled"):
        return {"action": "skipped", "reason": "disabled", "fired": []}
    budget_units = _threshold_units((cfg.get("thresholds") or {}).get("daily_budget"), label="daily_budget")
    if budget_units is None:
        return {"action": "skipped", "reason": "threshold_unset", "fired": []}

    day = local_day_key(ts)
    rows = conn.execute(
        """
        SELECT scope, currency, estimated_cost_units FROM daily_summary
        WHERE track = 'usage' AND day = ? AND estimated_cost_units IS NOT NULL
        """,
        (day,),
    ).fetchall()
    fired: list[dict[str, Any]] = []
    for row in rows:
        estimated = int(row["estimated_cost_units"])
        if estimated < budget_units:
            continue
        scope = str(row["scope"])
        status = notifications.fire(
            conn,
            kind="budget",
            rank=notifications.RANK_BUDGET,
            dedup_key=f"budget:{scope}:{day}",
            payload={
                "estimated_cost_units": estimated,
                "daily_budget_units": budget_units,
                "currency": row["currency"],
                "day": day,
            },
            ttl_ms=0,
            now=ts,
        )
        fired.append({"scope": scope, "currency": row["currency"], "status": status})
    return {"action": "evaluated", "day": day, "fired": fired}


# ---------------------------------------------------------------------------
# per-turn cost (M2/M3 settlement link — one notification per settled turn)
# ---------------------------------------------------------------------------

def evaluate_turn_cost(
    conn: sqlite3.Connection,
    *,
    dedup_key: str,
    estimated_cost_units: int | None,
    currency: str | None,
    model: str | None = None,
    cost_basis: str | None = None,
    now: int | None = None,
    home: str | None = None,
) -> dict[str, Any]:
    """Per-turn consumption notification, deduped by the turn's own dedup key.

    Fires only for priced turns (``estimated_cost_units is not None`` — an
    unpriced turn has nothing honest to show). ``thresholds.turn_cost_min``
    (decimal, None = no floor) suppresses negligible turns. TTL comes from
    ``bubbles.turn_cost_ttl_ms`` ([DSH] 消耗档自动关，默认 5s).
    """
    ts = now_ms() if now is None else int(now)
    cfg = _cfg(home)
    reminders = cfg.get("reminders") or {}
    if not _enabled(reminders, "turn_cost_enabled"):
        return {"action": "skipped", "reason": "disabled"}
    if estimated_cost_units is None:
        return {"action": "skipped", "reason": "unpriced"}
    floor_units = _threshold_units((cfg.get("thresholds") or {}).get("turn_cost_min"), label="turn_cost_min")
    if floor_units is not None and int(estimated_cost_units) < floor_units:
        return {"action": "skipped", "reason": "below_floor"}
    ttl_ms = (cfg.get("bubbles") or {}).get("turn_cost_ttl_ms", 5000)
    try:
        ttl = max(0, int(ttl_ms))
    except (TypeError, ValueError):
        ttl = 5000
    status = notifications.fire(
        conn,
        kind="turn_cost",
        rank=notifications.RANK_TURN_COST,
        dedup_key=f"turn:{dedup_key}",
        payload={
            "estimated_cost_units": int(estimated_cost_units),
            "currency": currency,
            "cost_basis": cost_basis,
            "model": model,
        },
        ttl_ms=ttl,
        now=ts,
    )
    return {"action": status, "dedup_key": f"turn:{dedup_key}"}
