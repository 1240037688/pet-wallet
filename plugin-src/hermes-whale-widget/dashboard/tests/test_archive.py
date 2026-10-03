"""ACC-10 slice — retention/archive executor: move-not-delete, caps, tick guard."""

from __future__ import annotations

import json

import pytest

from whale_core import archive
from whale_core.db import connect as db_connect
from whale_core.ingest import local_day_key
from whale_core.migrations import migrate

NOW_MS = 1_792_000_000_000
DAY_MS = 86_400_000


@pytest.fixture()
def conn(tmp_path):
    c = db_connect(tmp_path / "whale.db")
    migrate(c)
    yield c
    c.close()


def _seed_turn(conn, dedup_key, *, received_at):
    day = local_day_key(received_at)
    conn.execute(
        """
        INSERT INTO usage_event(dedup_key, session_id, turn_seq, source_event, model,
            input_tokens, output_tokens, reasoning_tokens, cache_read_tokens, cache_write_tokens,
            cumulative_json, raw_payload_json, day, received_at)
        VALUES (?, 's1', 1, 'message.complete', 'm', 1, 1, 0, 0, 0, '{}', '{}', ?, ?)
        """,
        (dedup_key, day, received_at),
    )
    conn.execute(
        """
        INSERT INTO turn_cost(dedup_key, session_id, turn_seq, model, estimated_cost_units,
            currency, cost_basis, status, day, settled_at)
        VALUES (?, 's1', 1, 'm', 0, 'none', 'token_only', 'final', ?, ?)
        """,
        (dedup_key, day, received_at),
    )


def test_expired_rows_move_to_archive_not_deleted(conn):
    _seed_turn(conn, "old", received_at=NOW_MS - 91 * DAY_MS)
    _seed_turn(conn, "recent", received_at=NOW_MS - 1 * DAY_MS)

    counts = archive.enforce_retention(conn, now=NOW_MS)

    assert counts["usage_event"] == 1 and counts["turn_cost"] == 1
    hot_events = [r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM usage_event")]
    hot_costs = [r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM turn_cost")]
    assert hot_events == ["recent"] and hot_costs == ["recent"]
    archived = [r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM usage_event_archive")]
    assert archived == ["old"]
    assert conn.execute("SELECT archived_at FROM turn_cost_archive").fetchone()[0] == NOW_MS
    # the move must be lossless (same content, plus the archived_at stamp)
    old = dict(conn.execute("SELECT * FROM usage_event_archive").fetchone())
    assert old["input_tokens"] == 1 and old["received_at"] == NOW_MS - 91 * DAY_MS


def test_retention_row_cap_moves_overflow(conn):
    for i in range(5):
        _seed_turn(conn, f"k{i}", received_at=NOW_MS - i * 60_000)
    counts = archive.enforce_retention(conn, now=NOW_MS, limits={"retention_max_rows": 2})
    hot = [r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM usage_event ORDER BY id")]
    assert hot == ["k3", "k4"]  # newest two stay hot
    assert counts["usage_event:rowcapped"] == 3
    archived = {r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM usage_event_archive")}
    assert archived == {"k0", "k1", "k2"}  # overflow moved, not deleted


def test_notification_and_watermark_deleted_at_expiry(conn):
    conn.execute(
        "INSERT INTO notification(kind, rank, dedup_key, payload_json, fired_at) VALUES ('error', 9, 'old-n', '{}', ?)",
        (NOW_MS - 31 * DAY_MS,),
    )
    conn.execute(
        "INSERT INTO notification(kind, rank, dedup_key, payload_json, fired_at) VALUES ('error', 9, 'new-n', '{}', ?)",
        (NOW_MS - 1 * DAY_MS,),
    )
    conn.execute(
        "INSERT INTO session_watermark(session_id, last_input, last_seen_at) VALUES ('stale', 5, ?)",
        (NOW_MS - 40 * DAY_MS,),
    )
    conn.execute(
        "INSERT INTO session_watermark(session_id, last_input, last_seen_at) VALUES ('fresh', 5, ?)",
        (NOW_MS - 1 * DAY_MS,),
    )
    archive.enforce_retention(conn, now=NOW_MS)
    keys = {r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM notification")}
    assert keys == {"new-n"}
    sessions = {r["session_id"] for r in conn.execute("SELECT session_id FROM session_watermark")}
    assert sessions == {"fresh"}


def test_daily_summary_moves_to_summary_archive(conn):
    conn.execute(
        """
        INSERT INTO daily_summary(scope, day, track, currency, estimated_cost_units, tokens_json, updated_at)
        VALUES ('usage:default:none', 'old-day', 'usage', 'none', NULL, ?, ?)
        """,
        (json.dumps({"total": {}, "models": {}}), NOW_MS - 400 * DAY_MS),
    )
    archive.enforce_retention(conn, now=NOW_MS)
    assert conn.execute("SELECT COUNT(*) FROM daily_summary").fetchone()[0] == 0
    assert conn.execute("SELECT day FROM summary_archive").fetchone()[0] == "old-day"


def test_maybe_daily_tick_runs_once_per_day(conn):
    assert archive.maybe_daily_tick(conn, now=NOW_MS) is True
    assert archive.maybe_daily_tick(conn, now=NOW_MS + 60_000) is False  # same local day
    assert archive.maybe_daily_tick(conn, now=NOW_MS + DAY_MS) is True  # next day
    row = conn.execute("SELECT value FROM whale_meta WHERE key='archive:last_tick_day'").fetchone()
    assert row[0] == local_day_key(NOW_MS + DAY_MS)


def test_archive_caps_drop_oldest(conn):
    for i in range(5):
        _seed_turn(conn, f"a{i}", received_at=NOW_MS - 91 * DAY_MS - i)
    archive.enforce_retention(conn, now=NOW_MS, limits={"archive_max_rows": 3})
    assert conn.execute("SELECT COUNT(*) FROM usage_event_archive").fetchone()[0] == 3
    # newest (last inserted id) survive, oldest dropped
    kept = [r["dedup_key"] for r in conn.execute("SELECT dedup_key FROM usage_event_archive ORDER BY id")]
    assert kept == ["a2", "a3", "a4"]
