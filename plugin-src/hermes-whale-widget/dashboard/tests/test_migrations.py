"""Migrations: v1 = full DATA_MODEL §7.2 DDL; idempotency, backup, fail-closed."""

from __future__ import annotations

import sqlite3

import pytest

from whale_core import db, migrations

EXPECTED_TABLES = {
    "whale_meta", "session_watermark",                      # support
    "provider", "model", "usage_event", "turn_cost",        # track①
    "balance_snapshot", "balance_adjustment",               # track②
    "daily_summary", "budget", "quota", "quota_observation", "notification",
    "usage_event_archive", "turn_cost_archive",
    "balance_snapshot_archive", "summary_archive",          # archives (DATA_MODEL §5)
}
EXPECTED_INDEXES = {
    "idx_usage_event_session", "idx_usage_event_day",
    "idx_turn_cost_day", "idx_balance_snapshot_scope",
}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _indexes(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def test_migrate_fresh_db_creates_full_v1_schema(tmp_path):
    conn = db.connect(tmp_path / "whale.db")
    version = migrations.migrate(conn)
    assert version == migrations.SCHEMA_VERSION == 1
    missing = EXPECTED_TABLES - _tables(conn)
    assert not missing, f"missing tables: {missing}"
    assert EXPECTED_INDEXES <= _indexes(conn)
    # version recorded in whale_meta
    row = conn.execute("SELECT value FROM whale_meta WHERE key='schema_version'").fetchone()
    assert row[0] == "1"
    conn.close()


def test_migrate_is_idempotent(tmp_path):
    conn = db.connect(tmp_path / "whale.db")
    assert migrations.migrate(conn) == 1
    tables_before = _tables(conn)
    assert migrations.migrate(conn) == 1  # no-op second run
    assert _tables(conn) == tables_before
    # a fresh handle (restart simulation) also stays at v1 with no duplicates
    conn.close()
    conn2 = db.connect(tmp_path / "whale.db")
    assert migrations.schema_version(conn2) == 1
    assert migrations.migrate(conn2) == 1
    assert _tables(conn2) == tables_before
    conn2.close()


def test_migrate_backs_up_existing_db_before_upgrade(tmp_path):
    """A pre-existing (non-empty) db file is backed up as whale.db.bak-<version>."""
    path = tmp_path / "whale.db"
    seed = sqlite3.connect(str(path))
    seed.execute("CREATE TABLE preexisting_user_data(x INTEGER)")
    seed.execute("INSERT INTO preexisting_user_data VALUES (42)")
    seed.commit()
    seed.close()

    conn = db.connect(path)
    assert migrations.migrate(conn) == 1
    conn.close()

    backup = path.with_name("whale.db.bak-1")
    assert backup.exists()
    check = sqlite3.connect(str(backup))
    assert check.execute("SELECT x FROM preexisting_user_data").fetchone()[0] == 42
    check.close()


def test_migration_failure_leaves_prior_state(tmp_path):
    """A failing migration rolls back and does not bump the version (fail-closed)."""
    conn = db.connect(tmp_path / "whale.db")
    assert migrations.migrate(conn) == 1
    tables_before = _tables(conn)

    broken = [(2, "CREATE TABLE v2_new(x TEXT); CREATE TABLE definitely_broken(-- oops")]
    original = list(migrations.MIGRATIONS)
    migrations.MIGRATIONS.append(broken[0])
    try:
        with pytest.raises(sqlite3.Error):
            migrations.migrate(conn)
        assert migrations.schema_version(conn) == 1
        assert _tables(conn) == tables_before
        assert "v2_new" not in _tables(conn)
    finally:
        migrations.MIGRATIONS[:] = original
    conn.close()


def test_connect_refuses_corrupt_db_and_quarantines(tmp_path):
    path = tmp_path / "whale.db"
    path.write_bytes(b"garbage bytes, not a database" * 64)
    with pytest.raises(db.LedgerCorruptError):
        db.connect(path)
    dumps = list(tmp_path.glob("whale.db.corrupt-*"))
    assert dumps, "corrupt file was not moved aside"
    assert not path.exists() or path.read_bytes() != b"garbage bytes, not a database" * 64


def test_foreign_keys_and_wal_pragmas_active(tmp_path):
    conn = db.connect(tmp_path / "whale.db")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
    conn.close()


def test_tracking_watermark_row_roundtrip(tmp_path):
    """Smoke: the v1 schema accepts a session_watermark row (shape check)."""
    conn = db.connect(tmp_path / "whale.db")
    migrations.migrate(conn)
    conn.execute(
        "INSERT INTO session_watermark(session_id, last_input, last_seen_at) VALUES ('s1', 10, 123)"
    )
    row = conn.execute("SELECT last_input, reset_count FROM session_watermark WHERE session_id='s1'").fetchone()
    assert tuple(row) == (10, 0)
    conn.close()
