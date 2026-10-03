"""Notifications — persistent dedup store + poll-fallback data source (M8).

The ``notification`` table is the single persistence point for "已提醒过"
(DR-14): a restart or event replay never re-rings because every reminder
carries a ``dedup_key`` under a UNIQUE constraint (DATA_MODEL §2.10) and
:func:`fire` turns a constraint hit into an honest ``duplicate`` status —
never an error, never a second bubble.

Rank order mirrors the bubble queue priority ([DSH] D3): budget 1 >
balance_low 2 > turn_cost 3 > waiting 4. ``ttl_ms = 0`` means persistent
(waiting-class bubbles stay until dismissed); ``> 0`` auto-expires.

Money-bearing payload fields follow DATA_MODEL §8.1: ``estimated_*`` /
``observed_*`` prefixes with ``*_units`` companions, plus an explicit
``currency`` — bare ``cost`` / ``spend`` / ``used`` keys never enter a
payload (guarded by ``whale_core.security.find_bare_money_keys`` in tests).

WS push is not wired in M8; the polling fallback (GET /wait-state's
``fired_dedup_keys`` + :func:`pending`) is the MVP transport — and the
mandatory one on OAuth remotes where ``ctx.socket`` is a no-op
(IMPLEMENTATION_PLAN §3.4, AUDIT §6.3).
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .clock import now_ms

# Bubble queue ranks ([DSH] D3; DATA_MODEL §2.10): 预算 1 > 预警 2 > 消耗 3 > 等待 4.
RANK_BUDGET = 1
RANK_BALANCE_LOW = 2
RANK_TURN_COST = 3
RANK_WAIT = 4

KINDS = (
    "budget", "balance_low", "turn_cost", "wait_input",
    "wait_approval", "error", "balance_change",
)

_MAX_DEDUP_KEY = 512


def fire(
    conn: sqlite3.Connection,
    *,
    kind: str,
    rank: int,
    dedup_key: str,
    payload: dict[str, Any] | None,
    ttl_ms: int = 0,
    now: int | None = None,
) -> str:
    """Insert one notification; a UNIQUE hit on ``dedup_key`` → ``duplicate``.

    Returns ``"fired"`` or ``"duplicate"``. ``payload`` is stored as JSON
    (Render Model input, sanitised by construction — callers only pass
    whitelisted, DATA_MODEL §8.1-named fields). ``ttl_ms = 0`` = persistent.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown notification kind: {kind}")
    if not isinstance(dedup_key, str) or not dedup_key or len(dedup_key) > _MAX_DEDUP_KEY:
        raise ValueError("notification dedup_key must be a non-empty string (<=512)")
    ts = now_ms() if now is None else int(now)
    payload_json = json.dumps(payload if payload is not None else {}, ensure_ascii=False, sort_keys=True)
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO notification(kind, rank, dedup_key, payload_json, fired_at, ttl_ms)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (kind, int(rank), dedup_key, payload_json, ts, max(0, int(ttl_ms))),
    )
    conn.commit()
    return "fired" if cur.rowcount else "duplicate"


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):  # defensive: payload is always an object
        payload = {}
    return {
        "kind": row["kind"],
        "rank": int(row["rank"]),
        "dedup_key": row["dedup_key"],
        "payload": payload,
        "fired_at": int(row["fired_at"]),
        "ttl_ms": int(row["ttl_ms"]),
    }


def _is_expired(fired_at: int, ttl_ms: int, ts: int) -> bool:
    return ttl_ms > 0 and (fired_at + ttl_ms) <= ts


def pending(conn: sqlite3.Connection, *, now: int | None = None) -> list[dict[str, Any]]:
    """Unexpired, un-dismissed notifications ordered by rank (then fired_at).

    The priority-queue data source: rank 1 (budget) first; within a rank,
    oldest first (consumption-class bubbles queue FIFO behind the newest,
    ordering applied client-side).
    """
    ts = now_ms() if now is None else int(now)
    rows = conn.execute(
        """
        SELECT kind, rank, dedup_key, payload_json, fired_at, ttl_ms
        FROM notification
        WHERE dismissed_at IS NULL
        ORDER BY rank ASC, fired_at ASC, id ASC
        """
    ).fetchall()
    return [
        _row_to_dict(row)
        for row in rows
        if not _is_expired(int(row["fired_at"]), int(row["ttl_ms"]), ts)
    ]


def active_dedup_keys(conn: sqlite3.Connection | None, *, now: int | None = None) -> list[str]:
    """Dedup keys of the currently-active (pending) notifications.

    Surfaced as ``fired_dedup_keys`` by GET /wait-state so the desktop half can
    align its "last shown" markers after a reload without re-ringing (DR-14).
    """
    if conn is None:
        return []
    return [item["dedup_key"] for item in pending(conn, now=now)]


def dismiss(conn: sqlite3.Connection, dedup_key: str, *, now: int | None = None) -> bool:
    """Mark one notification dismissed (no-op → False when absent/dismissed)."""
    ts = now_ms() if now is None else int(now)
    cur = conn.execute(
        "UPDATE notification SET dismissed_at = ? WHERE dedup_key = ? AND dismissed_at IS NULL",
        (ts, dedup_key),
    )
    conn.commit()
    return bool(cur.rowcount)


def dismiss_active(
    conn: sqlite3.Connection,
    *,
    kind: str | None = None,
    dedup_prefix: str | None = None,
    now: int | None = None,
) -> int:
    """Auto-dismiss every active notification matching the filters.

    Used by the rules engine for edge release (balance recovering ≥ threshold
    closes the standing low-balance bubble). Returns the dismissed count.
    """
    clauses = ["dismissed_at IS NULL"]
    params: list[Any] = []
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    if dedup_prefix is not None:
        clauses.append("dedup_key LIKE ?")
        params.append(dedup_prefix.replace("%", "") + "%")
    if len(clauses) == 1:
        raise ValueError("dismiss_active requires a kind or dedup_prefix filter")
    ts = now_ms() if now is None else int(now)
    cur = conn.execute(
        f"UPDATE notification SET dismissed_at = ? WHERE {' AND '.join(clauses)}",
        (ts, *params),
    )
    conn.commit()
    return int(cur.rowcount)


def count_all(conn: sqlite3.Connection) -> int:
    """Total notification rows (test/maintenance helper)."""
    row = conn.execute("SELECT COUNT(*) FROM notification").fetchone()
    return int(row[0]) if row is not None else 0
