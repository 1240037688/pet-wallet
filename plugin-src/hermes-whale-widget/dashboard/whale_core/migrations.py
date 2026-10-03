"""Schema migrations for whale.db (M0).

Migration v1 = the FULL DATA_MODEL §7.2 DDL (10 entities + 3 supporting
structures + archive tables), built in one shot to avoid development-time
schema churn (IMPLEMENTATION_PLAN M0 task 4). Later evolution goes v2+.

Rules (DATA_MODEL §7.3):
* each migration runs inside a single transaction;
* ``whale_meta.schema_version`` is bumped inside the same transaction;
* before writing a new version over an existing database, the file is backed
  up as ``whale.db.bak-<version>``;
* a failed migration leaves the previous state untouched (fail-closed).
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

_V1_DDL = """
-- ── supporting structures ──────────────────────────────────────────────
CREATE TABLE whale_meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE session_watermark (
  session_id    TEXT PRIMARY KEY,
  last_input    INTEGER NOT NULL DEFAULT 0,
  last_output   INTEGER NOT NULL DEFAULT 0,
  last_cache_read  INTEGER NOT NULL DEFAULT 0,
  last_cache_write INTEGER NOT NULL DEFAULT 0,
  last_reasoning   INTEGER NOT NULL DEFAULT 0,
  last_calls    INTEGER,
  last_seen_at  INTEGER NOT NULL,
  reset_count   INTEGER NOT NULL DEFAULT 0
);

-- ── track ① usage ledger ────────────────────────────────────────────────
CREATE TABLE provider (
  id TEXT PRIMARY KEY,
  template_key TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN('balance','quota','none')),
  currency TEXT NOT NULL,
  credential_ref TEXT NOT NULL,             -- reference name; NEVER the key itself
  credential_fingerprint TEXT NOT NULL,     -- sha256(key)[:24] = track② scope
  base_url_override TEXT,
  allow_custom_host INTEGER NOT NULL DEFAULT 0,
  match_ids TEXT,
  balance_json_paths TEXT,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE model (
  id TEXT PRIMARY KEY,
  display_name TEXT,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  pricing_json TEXT,                        -- {hit,miss,out,currency} per 1M tokens
  pricing_source TEXT NOT NULL DEFAULT 'none'
    CHECK(pricing_source IN('hermes_estimate','whale_pricing','none')),
  enabled INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE usage_event (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  turn_seq INTEGER NOT NULL,
  source_event TEXT NOT NULL DEFAULT 'message.complete',
  model TEXT NOT NULL,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  input_tokens INTEGER NOT NULL DEFAULT 0,
  output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0,
  cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  calls_delta INTEGER,
  context_used REAL,
  context_max REAL,
  context_percent REAL,
  cumulative_json TEXT NOT NULL,
  raw_payload_json TEXT NOT NULL,
  profile_name TEXT,
  day TEXT NOT NULL,
  received_at INTEGER NOT NULL
);
CREATE INDEX idx_usage_event_session ON usage_event(session_id, turn_seq);
CREATE INDEX idx_usage_event_day     ON usage_event(day);

CREATE TABLE turn_cost (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  turn_seq INTEGER NOT NULL,
  model TEXT NOT NULL,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  estimated_cost_units INTEGER NOT NULL,    -- fixed-point 1e8; naming red line: estimated_
  currency TEXT NOT NULL,
  cost_basis TEXT NOT NULL CHECK(cost_basis IN('hermes_estimate','whale_pricing','token_only')),
  pricing_snapshot_json TEXT,
  status TEXT NOT NULL DEFAULT 'final' CHECK(status IN('final','provisional')),
  day TEXT NOT NULL,
  settled_at INTEGER NOT NULL
);
CREATE INDEX idx_turn_cost_day ON turn_cost(day, currency);

-- ── track ② balance ledger ──────────────────────────────────────────────
CREATE TABLE balance_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider_id TEXT NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
  scope TEXT NOT NULL,
  currency TEXT NOT NULL,
  observed_balance_units INTEGER NOT NULL,  -- fixed-point 1e8
  granted_units INTEGER,                    -- NULL ≠ 0 (DATA_MODEL §2.5)
  topped_up_units INTEGER,                  -- NULL ≠ 0
  raw_response_json TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  fetch_state TEXT NOT NULL DEFAULT 'ok' CHECK(fetch_state IN('ok','stale_cache')),
  UNIQUE(provider_id, scope, currency, observed_balance_units, fetched_at)
);
CREATE INDEX idx_balance_snapshot_scope ON balance_snapshot(scope, currency, fetched_at);

CREATE TABLE balance_adjustment (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL,
  currency TEXT NOT NULL,
  day TEXT NOT NULL,
  credits_units INTEGER NOT NULL,
  other_debits_units INTEGER NOT NULL DEFAULT 0,
  implied_usage_units INTEGER NOT NULL,
  revision TEXT NOT NULL,
  correction_log_json TEXT,
  created_at INTEGER NOT NULL
);

-- ── aggregation & rules ────────────────────────────────────────────────
CREATE TABLE daily_summary (
  scope TEXT NOT NULL,
  day TEXT NOT NULL,
  track TEXT NOT NULL CHECK(track IN('usage','balance')),
  currency TEXT NOT NULL,
  opening_units INTEGER,
  last_units INTEGER,
  observed_spend_units INTEGER,
  credit_units INTEGER,
  estimated_cost_units INTEGER,
  tokens_json TEXT,
  partial INTEGER NOT NULL DEFAULT 0,
  observed_from INTEGER,
  observed_to INTEGER,
  gap_seconds INTEGER,
  deviation_units REAL,
  deviation_ratio REAL,
  needs_review INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY(scope, day, track)
);

CREATE TABLE budget (
  id TEXT PRIMARY KEY,
  scope_type TEXT NOT NULL CHECK(scope_type IN('global','provider','model')),
  scope_ref TEXT,
  period TEXT NOT NULL CHECK(period IN('daily','monthly')),
  amount_units INTEGER NOT NULL,
  currency TEXT NOT NULL,
  basis TEXT NOT NULL DEFAULT 'estimated_local'
    CHECK(basis IN('estimated_local','observed_balance')),
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);

CREATE TABLE quota (
  id TEXT PRIMARY KEY,
  provider_id TEXT NOT NULL REFERENCES provider(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN('api','cumulative','manual')),
  unit TEXT NOT NULL CHECK(unit IN('tokens','money','percent')),
  reset TEXT NOT NULL CHECK(reset IN('none','daily','monthly','window')),
  base_at INTEGER,
  manual_used_units INTEGER,
  windows_json TEXT,
  last_observed_at INTEGER,
  last_state TEXT CHECK(last_state IN('ok','unavailable','error') OR last_state IS NULL),
  last_error TEXT
);

CREATE TABLE quota_observation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  quota_id TEXT NOT NULL REFERENCES quota(id) ON DELETE CASCADE,
  window_key TEXT NOT NULL DEFAULT 'main',
  used_units INTEGER,
  total_units INTEGER,
  percent REAL,
  reset_at INTEGER,
  observed_at INTEGER NOT NULL
);

CREATE TABLE notification (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL CHECK(kind IN('budget','balance_low','turn_cost','wait_input',
                                   'wait_approval','error','balance_change')),
  rank INTEGER NOT NULL,
  dedup_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL,
  fired_at INTEGER NOT NULL,
  ttl_ms INTEGER NOT NULL DEFAULT 0,
  dismissed_at INTEGER
);

-- ── archives (DATA_MODEL §5): source structure + archived_at ───────────
CREATE TABLE usage_event_archive (
  id INTEGER PRIMARY KEY,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL, turn_seq INTEGER NOT NULL,
  source_event TEXT NOT NULL DEFAULT 'message.complete',
  model TEXT NOT NULL,
  provider_id TEXT,
  input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
  reasoning_tokens INTEGER NOT NULL DEFAULT 0,
  cache_read_tokens INTEGER NOT NULL DEFAULT 0, cache_write_tokens INTEGER NOT NULL DEFAULT 0,
  calls_delta INTEGER, context_used REAL, context_max REAL, context_percent REAL,
  cumulative_json TEXT NOT NULL, raw_payload_json TEXT NOT NULL,
  profile_name TEXT, day TEXT NOT NULL, received_at INTEGER NOT NULL,
  archived_at INTEGER NOT NULL
);

CREATE TABLE turn_cost_archive (
  id INTEGER PRIMARY KEY,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL, turn_seq INTEGER NOT NULL,
  model TEXT NOT NULL,
  provider_id TEXT,
  estimated_cost_units INTEGER NOT NULL,
  currency TEXT NOT NULL,
  cost_basis TEXT NOT NULL,
  pricing_snapshot_json TEXT,
  status TEXT NOT NULL DEFAULT 'final',
  day TEXT NOT NULL, settled_at INTEGER NOT NULL,
  archived_at INTEGER NOT NULL
);

CREATE TABLE balance_snapshot_archive (
  id INTEGER PRIMARY KEY,
  provider_id TEXT NOT NULL,
  scope TEXT NOT NULL, currency TEXT NOT NULL,
  observed_balance_units INTEGER NOT NULL,
  granted_units INTEGER, topped_up_units INTEGER,
  raw_response_json TEXT NOT NULL,
  fetched_at INTEGER NOT NULL,
  fetch_state TEXT NOT NULL DEFAULT 'ok',
  archived_at INTEGER NOT NULL
);

CREATE TABLE summary_archive (
  scope TEXT NOT NULL, day TEXT NOT NULL,
  track TEXT NOT NULL,
  currency TEXT NOT NULL,
  opening_units INTEGER, last_units INTEGER,
  observed_spend_units INTEGER, credit_units INTEGER,
  estimated_cost_units INTEGER, tokens_json TEXT,
  partial INTEGER NOT NULL DEFAULT 0,
  observed_from INTEGER, observed_to INTEGER, gap_seconds INTEGER,
  deviation_units REAL, deviation_ratio REAL,
  needs_review INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL,
  archived_at INTEGER NOT NULL,
  PRIMARY KEY(scope, day, track)
);
"""

# ── v2 (M3 pricing): unpriced cost rows must be NULL, never 0 ────────────
# The v1 NOT NULL on turn_cost.estimated_cost_units forced the M2 placeholder
# "0 + token_only" representation for "no price computed yet" — with M3 that
# would leak fake zeros into sums. v2 relaxes both money columns, adds the
# pricing_status reason column (unknown_model), migrates the M2 placeholder
# rows to honest NULLs, and adds the balance-track revision column (M4
# optimistic-concurrency, DATA_MODEL §2.6) plus the session cost watermark
# column used for cumulative-cost deltas.
_V2_DDL = """
CREATE TABLE turn_cost_v2 (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL,
  turn_seq INTEGER NOT NULL,
  model TEXT NOT NULL,
  provider_id TEXT REFERENCES provider(id) ON DELETE SET NULL,
  estimated_cost_units INTEGER,             -- v2: NULL = unpriced (unknown_model); never a fake 0
  currency TEXT,                            -- v2: NULL for unpriced rows
  cost_basis TEXT NOT NULL CHECK(cost_basis IN('hermes_estimate','whale_pricing','token_only')),
  pricing_status TEXT CHECK(pricing_status IN('hermes_estimate','whale_pricing','unknown_model')),
  pricing_snapshot_json TEXT,
  status TEXT NOT NULL DEFAULT 'final' CHECK(status IN('final','provisional')),
  day TEXT NOT NULL,
  settled_at INTEGER NOT NULL
);
INSERT INTO turn_cost_v2(
    id, dedup_key, session_id, turn_seq, model, provider_id,
    estimated_cost_units, currency, cost_basis, pricing_status,
    pricing_snapshot_json, status, day, settled_at)
SELECT id, dedup_key, session_id, turn_seq, model, provider_id,
    CASE WHEN cost_basis = 'token_only' THEN NULL ELSE estimated_cost_units END,
    CASE WHEN cost_basis = 'token_only' THEN NULL ELSE currency END,
    cost_basis,
    CASE WHEN cost_basis = 'token_only' THEN 'unknown_model' ELSE cost_basis END,
    pricing_snapshot_json, status, day, settled_at
FROM turn_cost;
DROP TABLE turn_cost;
ALTER TABLE turn_cost_v2 RENAME TO turn_cost;
CREATE INDEX idx_turn_cost_day ON turn_cost(day, currency);

CREATE TABLE turn_cost_archive_v2 (
  id INTEGER PRIMARY KEY,
  dedup_key TEXT NOT NULL UNIQUE,
  session_id TEXT NOT NULL, turn_seq INTEGER NOT NULL,
  model TEXT NOT NULL,
  provider_id TEXT,
  estimated_cost_units INTEGER,
  currency TEXT,
  cost_basis TEXT NOT NULL,
  pricing_status TEXT,
  pricing_snapshot_json TEXT,
  status TEXT NOT NULL DEFAULT 'final',
  day TEXT NOT NULL, settled_at INTEGER NOT NULL,
  archived_at INTEGER NOT NULL
);
INSERT INTO turn_cost_archive_v2(
    id, dedup_key, session_id, turn_seq, model, provider_id,
    estimated_cost_units, currency, cost_basis, pricing_status,
    pricing_snapshot_json, status, day, settled_at, archived_at)
SELECT id, dedup_key, session_id, turn_seq, model, provider_id,
    CASE WHEN cost_basis = 'token_only' THEN NULL ELSE estimated_cost_units END,
    CASE WHEN cost_basis = 'token_only' THEN NULL ELSE currency END,
    cost_basis,
    CASE WHEN cost_basis = 'token_only' THEN 'unknown_model' ELSE cost_basis END,
    pricing_snapshot_json, status, day, settled_at, archived_at
FROM turn_cost_archive;
DROP TABLE turn_cost_archive;
ALTER TABLE turn_cost_archive_v2 RENAME TO turn_cost_archive;

ALTER TABLE daily_summary ADD COLUMN revision TEXT;
ALTER TABLE session_watermark ADD COLUMN last_cost_units REAL;
"""

# (version, sql). Append-only; never edit an applied migration.
MIGRATIONS: list[tuple[int, str]] = [(1, _V1_DDL), (2, _V2_DDL)]


def schema_version(conn: sqlite3.Connection) -> int:
    """Current schema_version from whale_meta; 0 if the table is absent."""
    try:
        row = conn.execute("SELECT value FROM whale_meta WHERE key='schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def migrate(conn: sqlite3.Connection) -> int:
    """Apply pending migrations; returns the resulting schema version."""
    current = schema_version(conn)
    target = MIGRATIONS[-1][0]
    if current >= target:
        return current
    db_file = _main_db_file(conn)
    for version, ddl in MIGRATIONS:
        if version <= current:
            continue
        _backup_before_upgrade(db_file, version)
        script = (
            "BEGIN;\n"
            f"{ddl}\n"
            "INSERT INTO whale_meta(key, value) VALUES('schema_version', "
            f"'{version}') ON CONFLICT(key) DO UPDATE SET value=excluded.value;\n"
            "COMMIT;"
        )
        try:
            conn.executescript(script)
        except sqlite3.Error:
            conn.rollback()
            raise
        current = version
    return current


def _main_db_file(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute("PRAGMA database_list").fetchone()
    if row is None:
        return None
    name = row[2]
    if not name:  # ':memory:' or unnamed
        return None
    return Path(str(name))


def _backup_before_upgrade(db_file: Path | None, version: int) -> None:
    """Copy whale.db → whale.db.bak-<version> before writing a new schema."""
    if db_file is None or not db_file.exists() or db_file.stat().st_size == 0:
        return  # brand-new database: nothing to preserve
    backup = db_file.with_name(f"{db_file.name}.bak-{version}")
    shutil.copy2(db_file, backup)
