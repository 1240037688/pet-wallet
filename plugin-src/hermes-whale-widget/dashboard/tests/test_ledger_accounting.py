"""ACC-01..05 + INT-02 slices — ledger settlement correctness (M2).

Every test answers DATA_MODEL §3.4's question: does this scenario double-charge?
"""

from __future__ import annotations

import json

import pytest

from conftest import MOUNT_PREFIX
from whale_core import api as whale_api, clock
from whale_core.db import connect as db_connect
from whale_core.ingest import (
    ingest_turn,
    local_day_key,
    _compute_delta,
    _get_watermark,
)

BASE_MS = 1_792_000_000_000  # fixed epoch ms; day key derived per local tz


def _turn(session_id="s1", *, received_at=None, model="deepseek-chat", status="complete",
          after_reconnect=False, replayed=False, **usage):
    return {
        "session_id": session_id,
        "profile": "default",
        "model": model,
        "usage": usage or {"input": 100, "output": 50, "reasoning": 10, "cache_read": 5, "cache_write": 2, "calls": 3},
        "received_at": received_at if received_at is not None else BASE_MS,
        "status": status,
        "after_reconnect": after_reconnect,
        "replayed": replayed,
    }


@pytest.fixture()
def conn(tmp_path):
    """Fresh migrated ledger file (direct whale_core.ingest-level tests)."""
    from whale_core import migrations

    c = db_connect(tmp_path / "whale.db")
    migrations.migrate(c)
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _pin_clock():
    clock.set_clock(lambda: BASE_MS / 1000.0)
    yield
    clock.reset_clock()


def _rows(conn, table, order="id"):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY {order}").fetchall()]


# ---------------------------------------------------------------------------
# direct-ledger tests (whale_core.ingest)
# ---------------------------------------------------------------------------


def test_acc01_usage_event_and_turn_cost_written(conn):
    res = ingest_turn(conn, _turn())
    # M8 settled contract: accepted responses also carry the settled array
    assert res["status"] == "accepted"
    assert res["accepted"] == 1 and res["duplicate"] == 0 and res["aligned"] is False
    assert len(res["settled"]) == 1

    events = _rows(conn, "usage_event")
    costs = _rows(conn, "turn_cost")
    assert len(events) == 1 and len(costs) == 1

    ev = events[0]
    assert ev["turn_seq"] == 1
    assert ev["source_event"] == "message.complete"
    assert ev["input_tokens"] == 100 and ev["output_tokens"] == 50
    assert ev["reasoning_tokens"] == 10 and ev["cache_read_tokens"] == 5 and ev["cache_write_tokens"] == 2
    assert ev["calls_delta"] == 3
    assert ev["day"] == local_day_key(BASE_MS)
    assert ev["received_at"] == BASE_MS
    cumulative = json.loads(ev["cumulative_json"])
    assert cumulative["input"] == 100 and cumulative["cost_usd"] is None  # _turn has no cost_usd
    assert json.loads(ev["raw_payload_json"])["input"] == 100

    tc = costs[0]
    assert tc["dedup_key"] == ev["dedup_key"]
    # M3 pricing landed: deepseek-chat resolves from the builtin CNY table
    # (miss 2 / hit 0.04 / out 8 per 1M; reasoning ⊆ output, no cache-write
    # billing) → 100×2 + 5×0.04 + 50×8 = 600.20 CNY-e8 units = 60_020
    assert tc["cost_basis"] == "whale_pricing"
    assert tc["pricing_status"] == "whale_pricing"
    assert tc["estimated_cost_units"] == 60_020
    assert tc["pricing_snapshot_json"] is not None
    assert tc["currency"] == "CNY"
    assert tc["status"] == "final"


def test_acc02_duplicate_replay_never_double_counts(conn):
    res1 = ingest_turn(conn, _turn())
    res2 = ingest_turn(conn, _turn())
    res3 = ingest_turn(conn, _turn())
    assert res1["status"] == "accepted"
    assert res2["status"] == "duplicate" and res2["duplicate"] == 1
    assert res3["status"] == "duplicate"
    assert len(_rows(conn, "usage_event")) == 1
    assert len(_rows(conn, "turn_cost")) == 1


def test_acc02_duplicate_with_drifted_minute(conn):
    """Reconnect replay: same snapshot, receive minute drifted (fuzzy window)."""
    ingest_turn(conn, _turn())
    drifted = _turn(received_at=BASE_MS + 4 * 60_000)
    res = ingest_turn(conn, drifted)
    assert res["status"] == "duplicate"
    assert len(_rows(conn, "usage_event")) == 1


def test_acc02_distinct_turns_beyond_window_settle(conn):
    ingest_turn(conn, _turn())
    nxt = _turn(received_at=BASE_MS + 20 * 60_000, input=150, output=80)
    res = ingest_turn(conn, nxt)
    assert res["status"] == "accepted"
    assert len(_rows(conn, "usage_event")) == 2


def test_acc03_restart_replay_no_duplicate_and_seq_continues(conn):
    ingest_turn(conn, _turn())
    ingest_turn(conn, _turn(received_at=BASE_MS + 60_000, input=150))

    # simulate process restart: a NEW connection over the same file
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn.close()
    conn2 = db_connect(path)
    from whale_core import migrations

    migrations.migrate(conn2)

    # replay the SAME batch (same received_at) → duplicates, no new rows
    assert ingest_turn(conn2, _turn())["status"] == "duplicate"
    assert ingest_turn(conn2, _turn(received_at=BASE_MS + 60_000, input=150))["status"] == "duplicate"

    # a genuinely new turn continues the seq
    assert ingest_turn(conn2, _turn(received_at=BASE_MS + 120_000, input=200))["accepted"] == 1
    rows = _rows(conn2, "usage_event")
    assert [r["turn_seq"] for r in rows] == [1, 2, 3]
    conn2.close()


def test_acc04_multi_turn_deltas_are_adjacent_snapshot_diffs(conn):
    ingest_turn(conn, _turn(input=100, output=50, calls=3))
    ingest_turn(conn, _turn(received_at=BASE_MS + 60_000, input=260, output=50, calls=7))
    ingest_turn(conn, _turn(received_at=BASE_MS + 120_000, input=300, output=90, calls=9))
    rows = _rows(conn, "usage_event")
    assert [(r["turn_seq"], r["input_tokens"], r["output_tokens"], r["calls_delta"]) for r in rows] == [
        (1, 100, 50, 3),
        (2, 160, 0, 4),
        (3, 40, 40, 2),
    ]


def test_acc04_multi_session_no_cross_accounting(conn):
    """Main session + subagent session ids settle into independent buckets."""
    arrivals = [
        ("s1", 0, 10),   # s1 turn 1
        ("s2", 1, 10),   # s2 turn 1
        ("s2", 2, 20),   # s2 turn 2 (cumulative grows)
        ("s1", 3, 20),   # s1 turn 2, interleaved arrival
    ]
    for session_id, offset, snapshot in arrivals:
        ingest_turn(conn, _turn(session_id=session_id, received_at=BASE_MS + offset * 60_000, input=snapshot))
    rows = _rows(conn, "usage_event")
    by_session = {}
    for row in rows:
        by_session.setdefault(row["session_id"], []).append(row)
    assert sorted(by_session) == ["s1", "s2"]
    for session_rows in by_session.values():
        assert [r["turn_seq"] for r in session_rows] == [1, 2]  # per-session counting
        assert all(r["input_tokens"] == 10 for r in session_rows)  # deltas, never absolutes
    # order-independence of the totals
    total = sum(r["input_tokens"] for r in rows)
    assert total == 40


def test_acc04_multi_model_per_turn_model_recorded(conn):
    ingest_turn(conn, _turn(model="deepseek-chat", input=100))
    ingest_turn(conn, _turn(model="deepseek-reasoner", received_at=BASE_MS + 60_000, input=120))
    rows = _rows(conn, "usage_event")
    assert [r["model"] for r in rows] == ["deepseek-chat", "deepseek-reasoner"]
    assert rows[1]["input_tokens"] == 20  # delta vs same session watermark


def test_acc05_counter_reset_provisional_no_negative(conn):
    ingest_turn(conn, _turn(input=1000, output=500))
    # gateway restart wiped the counters mid-session: snapshot below watermark
    res = ingest_turn(conn, _turn(received_at=BASE_MS + 60_000, input=40, output=30))
    assert res["status"] == "accepted"
    rows = _rows(conn, "turn_cost")
    assert rows[-1]["status"] == "provisional"
    assert rows[-1]["cost_basis"] == "token_only"
    ev = _rows(conn, "usage_event")[-1]
    assert ev["input_tokens"] == 40 and ev["output_tokens"] == 30  # post-reset absolute, never negative
    wm = _get_watermark(conn, "s1")
    assert wm["reset_count"] == 1 and wm["input"] == 40

    # the following normal turn recovers final status with a correct delta
    ingest_turn(conn, _turn(received_at=BASE_MS + 120_000, input=120, output=60))
    rows = _rows(conn, "turn_cost")
    assert rows[-1]["status"] == "final"
    assert _rows(conn, "usage_event")[-1]["input_tokens"] == 80


def test_after_reconnect_aligns_without_settling(conn):
    ingest_turn(conn, _turn(input=100))
    aligned = ingest_turn(conn, _turn(received_at=BASE_MS + 300_000, input=400, after_reconnect=True))
    assert aligned == {"status": "accepted", "accepted": 0, "duplicate": 0, "aligned": True}
    assert len(_rows(conn, "usage_event")) == 1  # alignment wrote nothing
    # next turn's delta measured against the ALIGNED watermark
    res = ingest_turn(conn, _turn(received_at=BASE_MS + 360_000, input=450))
    ev = _rows(conn, "usage_event")[-1]
    assert res["accepted"] == 1 and ev["turn_seq"] == 2 and ev["input_tokens"] == 50


def test_replayed_envelope_aligns_without_settling(conn):
    ingest_turn(conn, _turn(input=100))
    res = ingest_turn(conn, _turn(received_at=BASE_MS + 60_000, input=100, replayed=True))
    assert res["aligned"] is True
    assert len(_rows(conn, "usage_event")) == 1


def test_null_aware_fields_never_fabricate(conn):
    res = ingest_turn(conn, _turn(input=100))  # only input present
    ev = _rows(conn, "usage_event")[0]
    assert res["accepted"] == 1
    assert ev["input_tokens"] == 100
    assert ev["output_tokens"] == 0 and ev["reasoning_tokens"] == 0  # absent → no delta
    assert ev["calls_delta"] is None  # absent calls stays NULL, not 0
    assert ev["context_used"] is None and ev["context_percent"] is None


def test_all_null_usage_is_skipped_not_recorded(conn):
    res = ingest_turn(conn, _turn(input=None, output=None))
    assert res["skipped"] is True and res["accepted"] == 0
    assert _rows(conn, "usage_event") == []
    assert _get_watermark(conn, "s1")["input"] == 0


def test_compute_delta_reset_semantics():
    wm = {"input": 100, "output": 50, "cache_read": 0, "cache_write": 0, "reasoning": 0, "last_calls": 5, "reset_count": 0}
    deltas, reset = _compute_delta({"input": 80, "output": 70, "calls": 3}, wm)
    # reset signalled by input (80 < 100) AND calls (3 < 5); output grew normally
    assert reset is True
    assert deltas == {"input": 80, "output": 20, "cache_read": 0, "cache_write": 0, "reasoning": 0, "calls": 3}
    deltas, reset = _compute_delta({"input": 180, "output": 50, "calls": 9}, wm)
    assert reset is False
    assert deltas["input"] == 80 and deltas["output"] == 0 and deltas["calls"] == 4
    deltas, reset = _compute_delta({"output": 60}, wm)  # absent fields → no delta
    assert reset is False
    assert deltas["input"] == 0 and deltas["calls"] is None and deltas["output"] == 10


def test_daily_summary_rollup_per_model(conn):
    ingest_turn(conn, _turn(model="deepseek-chat", input=100, output=50))
    ingest_turn(conn, _turn(model="deepseek-reasoner", received_at=BASE_MS + 60_000, input=10))
    # M3: scope carries the settlement currency — the priced turn books CNY,
    # the reset turn (token_only) books the 'none' scope; both coexist.
    rows = {r["scope"]: r for r in conn.execute("SELECT * FROM daily_summary WHERE track='usage'").fetchall()}
    assert set(rows) == {"usage:default:CNY", "usage:default:none"}
    cny = rows["usage:default:CNY"]
    assert cny["day"] == local_day_key(BASE_MS)
    assert cny["estimated_cost_units"] == 60_000  # only the priced turn
    data = json.loads(cny["tokens_json"])
    assert data["total"]["input"] == 100 and data["total"]["output"] == 50
    assert data["models"]["deepseek-chat"]["input"] == 100
    none_row = rows["usage:default:none"]
    assert json.loads(none_row["tokens_json"])["total"]["input"] == 10  # reset absolute


# ---------------------------------------------------------------------------
# API-level duplicates/restart (L3 path through the REST door)
# ---------------------------------------------------------------------------


def test_api_duplicate_replay_only_one_row(client):
    conn = _runtime_conn(client)
    turn = _turn(session_id="api-sess")
    first = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=turn)
    replay = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=turn)
    assert first.json()["status"] == "accepted"
    assert replay.json() == {"status": "duplicate", "accepted": 0, "duplicate": 1, "aligned": False}
    assert len(_rows(conn, "usage_event")) == 1


def test_api_restart_replay_no_double_count(client):
    conn = _runtime_conn(client)
    turn = _turn(session_id="api-sess")
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=turn)

    # simulate restart: close + reopen the runtime (new db handle)
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    conn.close()
    whale_api.reset_runtime()
    conn2 = _runtime_conn(client)
    assert conn2.execute("PRAGMA database_list").fetchone()[2] == db_path

    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=turn)
    assert res.json()["status"] == "duplicate"
    assert len(_rows(conn2, "usage_event")) == 1


def test_ingest_response_has_no_bare_money_keys(client):
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=_turn(session_id="lint-sess"))
    from whale_core.security import find_bare_money_keys

    assert find_bare_money_keys(res.json()) == []


def _runtime_conn(client):
    client.get(f"{MOUNT_PREFIX}/health")  # force lazy runtime init
    return whale_api._rt.conn
