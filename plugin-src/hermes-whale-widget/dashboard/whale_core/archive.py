"""Archive — retention policy executor (DATA_MODEL §5, M2 minimal).

Thresholds (DATA_MODEL §5.1, DSH magnitude):
  * usage_event / turn_cost: 90 days (or 20k rows, whichever first) → moved
    into the ``*_archive`` tables — archived, never destroyed; archives
    themselves capped at 200k rows (oldest dropped beyond the cap);
  * balance_snapshot: 90 days → archive (rows appear with M4);
  * daily_summary: 365 days → ``summary_archive``;
  * notification: 30 days → deleted outright (no audit value);
  * session_watermark: inactive 30 days → deleted.

Execution model: ``enforce_retention`` is the pure executor (injectable now);
``maybe_daily_tick`` runs it at most once per LOCAL day (guard stored in
``whale_meta``) and is called opportunistically after turn settlements
("turn 结算顺手 prune") — single-writer discipline, no timers (AGENTS.md §8).
All limits are injectable for tests (``limits=``), the defaults are the
documented production values.
"""

from __future__ import annotations

from .clock import now_ms
from .ingest import local_day_key
from .logging_setup import get_logger

log = get_logger("archive")

RETENTION_DAYS = 90
RETENTION_MAX_ROWS = 20_000
ARCHIVE_MAX_ROWS = 200_000
SUMMARY_DAYS = 365
NOTIFICATION_DAYS = 30
WATERMARK_IDLE_DAYS = 30

_TICK_KEY = "archive:last_tick_day"

_DAY_MS = 86_400_000

# (hot table, monotonic ms column) pairs that move into <table>_archive
_MOVE_TABLES = {
    "usage_event": "received_at",
    "turn_cost": "settled_at",
    "balance_snapshot": "fetched_at",
}


def enforce_retention(conn, *, now: int | None = None, limits: dict[str, int] | None = None) -> dict[str, int]:
    """Move/delete expired rows; returns per-table affected-row counts."""
    ts = now_ms() if now is None else int(now)
    cfg = {
        "retention_days": RETENTION_DAYS,
        "retention_max_rows": RETENTION_MAX_ROWS,
        "archive_max_rows": ARCHIVE_MAX_ROWS,
        "summary_days": SUMMARY_DAYS,
        "notification_days": NOTIFICATION_DAYS,
        "watermark_idle_days": WATERMARK_IDLE_DAYS,
    }
    if limits:
        cfg.update(limits)
    counts: dict[str, int] = {}

    cutoff = ts - int(cfg["retention_days"]) * _DAY_MS
    for table, ms_column in _MOVE_TABLES.items():
        archive = f"{table}_archive"
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        col_list = ", ".join(columns)
        with conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {archive} ({col_list}, archived_at) "
                f"SELECT {col_list}, ? FROM {table} WHERE {ms_column} < ?",
                (ts, cutoff),
            )
            counts[table] = int(cur.rowcount or 0)
            conn.execute(f"DELETE FROM {table} WHERE {ms_column} < ?", (cutoff,))

    # hot-table row cap (20k rows, whichever limit binds first) — rows MOVE to
    # the archive, never destroyed (DATA_MODEL §5.1)
    for table, ms_column in (("usage_event", "received_at"), ("turn_cost", "settled_at")):
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        col_list = ", ".join(columns)
        overflow = f"SELECT id FROM {table} ORDER BY id DESC LIMIT -1 OFFSET ?"
        with conn:
            cur = conn.execute(
                f"INSERT OR IGNORE INTO {table}_archive ({col_list}, archived_at) "
                f"SELECT {col_list}, ? FROM {table} WHERE id IN ({overflow})",
                (ts, int(cfg["retention_max_rows"])),
            )
            counts[f"{table}:rowcapped"] = int(cur.rowcount or 0)
            conn.execute(f"DELETE FROM {table} WHERE id IN ({overflow})", (int(cfg["retention_max_rows"]),))

    # daily_summary → summary_archive (long-term queryable, DATA_MODEL §5.1)
    summary_cutoff = ts - int(cfg["summary_days"]) * _DAY_MS
    with conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO summary_archive
                (scope, day, track, currency, opening_units, last_units,
                 observed_spend_units, credit_units, estimated_cost_units, tokens_json,
                 partial, observed_from, observed_to, gap_seconds,
                 deviation_units, deviation_ratio, needs_review, updated_at, archived_at)
            SELECT scope, day, track, currency, opening_units, last_units,
                   observed_spend_units, credit_units, estimated_cost_units, tokens_json,
                   partial, observed_from, observed_to, gap_seconds,
                   deviation_units, deviation_ratio, needs_review, updated_at, ?
            FROM daily_summary WHERE updated_at < ?
            """,
            (ts, summary_cutoff),
        )
        counts["daily_summary"] = int(cur.rowcount or 0)
        conn.execute("DELETE FROM daily_summary WHERE updated_at < ?", (summary_cutoff,))

    # notification: deleted outright (no audit value)
    with conn:
        cur = conn.execute(
            "DELETE FROM notification WHERE fired_at < ?",
            (ts - int(cfg["notification_days"]) * _DAY_MS,),
        )
        counts["notification"] = int(cur.rowcount or 0)

    # session watermark: deleted after the idle window
    with conn:
        cur = conn.execute(
            "DELETE FROM session_watermark WHERE last_seen_at < ?",
            (ts - int(cfg["watermark_idle_days"]) * _DAY_MS,),
        )
        counts["session_watermark"] = int(cur.rowcount or 0)

    # archive caps: drop the OLDEST beyond the cap (DSH behaviour)
    for archive in ("usage_event_archive", "turn_cost_archive", "balance_snapshot_archive"):
        with conn:
            cur = conn.execute(
                f"DELETE FROM {archive} WHERE id IN "
                f"(SELECT id FROM {archive} ORDER BY id DESC LIMIT -1 OFFSET ?)",
                (int(cfg["archive_max_rows"]),),
            )
            counts[f"{archive}:capped"] = int(cur.rowcount or 0)
    with conn:
        cur = conn.execute(
            "DELETE FROM summary_archive WHERE rowid IN "
            "(SELECT rowid FROM summary_archive ORDER BY updated_at DESC, rowid DESC LIMIT -1 OFFSET ?)",
            (int(cfg["archive_max_rows"]),),
        )
        counts["summary_archive:capped"] = int(cur.rowcount or 0)

    return counts


def maybe_daily_tick(conn, *, now: int | None = None) -> bool:
    """Run retention at most once per local day; True when it ran."""
    ts = now_ms() if now is None else int(now)
    day = local_day_key(ts)
    row = conn.execute("SELECT value FROM whale_meta WHERE key = ?", (_TICK_KEY,)).fetchone()
    if row is not None and row["value"] == day:
        return False
    try:
        enforce_retention(conn, now=ts)
    except Exception as exc:  # noqa: BLE001 - prune must never break settlement
        log.warning("archive tick failed: %s", exc)
        return False
    conn.execute(
        "INSERT INTO whale_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (_TICK_KEY, day),
    )
    conn.commit()
    return True
