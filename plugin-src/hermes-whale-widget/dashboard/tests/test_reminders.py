"""REM domain (M8) — reminder rules engine + persistent dedup + hook isolation.

Covers:

* notification store: fire/pending/dismiss with UNIQUE dedup (DR-14);
* balance_low: trigger / recovery auto-dismiss / same-day silence / cross-day
  re-arm (dedup ``balance_low:{scope}:{day}``);
* daily budget: per-scope fire (currencies never merged), cross-day reset;
* turn_cost: toggle, floor threshold, unpriced turns, turn-dedup inheritance;
* the two minimal hooks: ingest settlement + balance snapshot — a rules crash
  must never change return values or transaction semantics;
* the M8 ``settled`` cross-package contract (accepted responses only, exact
  field names, old fields preserved, duplicates carry no settled);
* restart/replay: a fresh runtime handle cannot re-ring (DR-14);
* REST naming lint (DATA_MODEL §8.1) over the new surfaces.
"""

from __future__ import annotations

import json

import pytest

from conftest import MOUNT_PREFIX
from whale_core import (
    clock,
    config,
    db,
    ingest,
    migrations,
    notifications,
    rules,
)
from whale_core.security import find_bare_money_keys

DAY1 = 1_792_000_000_000  # arbitrary fixed epoch ms
DAY2 = DAY1 + 86_400_000
DAY1_KEY = ingest.local_day_key(DAY1)  # local day keys derived, never hardcoded
DAY2_KEY = ingest.local_day_key(DAY2)


@pytest.fixture()
def conn(hermes_home):
    """Direct ledger connection (rule-level tests bypass the REST layer)."""
    c = db.connect(hermes_home / "whale-widget" / "whale.db")
    migrations.migrate(c)
    yield c
    c.close()


@pytest.fixture()
def pinned_clock():
    """Injectable clock (TEST_PLAN §2.3) — state dict drives ``now_ms``."""
    state = {"now": DAY1}
    clock.set_clock(lambda: state["now"] / 1000.0)
    yield state
    clock.reset_clock()


def runtime_conn():
    from whale_core import api as whale_api

    return whale_api._ensure_runtime().conn


def notif_rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM notification ORDER BY id").fetchall()]


def set_threshold(home, **values):
    thresholds = config.load_config(home)["thresholds"]
    thresholds.update(values)
    config.save_config({"thresholds": thresholds}, home=home)


def make_turn(*, session_id="sess-rem", cost_usd=0.5, received_at=DAY1, model="deepseek-chat", **over):
    payload = {
        "session_id": session_id,
        "profile": "default",
        "model": model,
        "usage": {
            "input": 100, "output": 50, "reasoning": 0, "cache_read": 0, "cache_write": 0,
            "calls": 1, "cost_usd": cost_usd,
        },
        "received_at": received_at,
        "status": "complete",
        "after_reconnect": False,
    }
    payload.update(over)
    return payload


# ---------------------------------------------------------------------------
# notification store (persistent dedup, DR-14)
# ---------------------------------------------------------------------------


def test_fire_then_duplicate_same_dedup_key(conn):
    first = notifications.fire(conn, kind="budget", rank=1, dedup_key="budget:s:2026-10-03", payload={})
    again = notifications.fire(conn, kind="budget", rank=1, dedup_key="budget:s:2026-10-03", payload={})
    assert first == "fired"
    assert again == "duplicate"
    assert len(notif_rows(conn)) == 1


def test_pending_orders_by_rank_and_filters_dismissed_expired(conn):
    now = DAY1
    notifications.fire(conn, kind="turn_cost", rank=3, dedup_key="turn:a", payload={}, ttl_ms=1000, now=now)
    notifications.fire(conn, kind="budget", rank=1, dedup_key="budget:b", payload={}, now=now)
    notifications.fire(conn, kind="balance_low", rank=2, dedup_key="low:c", payload={}, now=now)
    notifications.fire(conn, kind="wait_input", rank=4, dedup_key="wait:d", payload={}, now=now)

    keys = [item["dedup_key"] for item in notifications.pending(conn, now=now + 100)]
    assert keys == ["budget:b", "low:c", "turn:a", "wait:d"]  # rank 1 > 2 > 3 > 4

    # expired ttl (turn_cost) drops out; dismissed rows drop out
    assert [i["dedup_key"] for i in notifications.pending(conn, now=now + 2000)] == ["budget:b", "low:c", "wait:d"]
    assert notifications.dismiss(conn, "budget:b", now=now + 2000) is True
    assert notifications.dismiss(conn, "budget:b", now=now + 2000) is False  # idempotent
    assert [i["dedup_key"] for i in notifications.pending(conn, now=now + 2000)] == ["low:c", "wait:d"]


def test_pending_payload_money_naming_lint(conn):
    """DATA_MODEL §8.1: stored payloads never carry bare cost/spend/used keys."""
    notifications.fire(
        conn, kind="balance_low", rank=2, dedup_key="low:x", now=DAY1,
        payload={"observed_balance_units": 1, "balance_low_threshold_units": 2, "currency": "CNY"},
    )
    notifications.fire(
        conn, kind="turn_cost", rank=3, dedup_key="turn:x", now=DAY1,
        payload={"estimated_cost_units": 3, "currency": "CNY", "cost_basis": "hermes_estimate"},
    )
    for row in notif_rows(conn):
        assert find_bare_money_keys(json.loads(row["payload_json"])) == []


def test_fire_rejects_unknown_kind_and_empty_key(conn):
    with pytest.raises(ValueError):
        notifications.fire(conn, kind="nonsense", rank=1, dedup_key="k", payload={})
    with pytest.raises(ValueError):
        notifications.fire(conn, kind="budget", rank=1, dedup_key="", payload={})


def test_dismiss_active_by_kind_and_prefix(conn):
    notifications.fire(conn, kind="balance_low", rank=2, dedup_key="balance_low:s1:2026-10-03", payload={}, now=DAY1)
    notifications.fire(conn, kind="balance_low", rank=2, dedup_key="balance_low:s2:2026-10-03", payload={}, now=DAY1)
    notifications.fire(conn, kind="budget", rank=1, dedup_key="budget:s1:2026-10-03", payload={}, now=DAY1)
    dismissed = notifications.dismiss_active(
        conn, kind="balance_low", dedup_prefix="balance_low:s1:", now=DAY1,
    )
    assert dismissed == 1
    keys = {row["dedup_key"]: row["dismissed_at"] for row in notif_rows(conn)}
    assert keys["balance_low:s1:2026-10-03"] is not None
    assert keys["balance_low:s2:2026-10-03"] is None
    assert keys["budget:s1:2026-10-03"] is None


# ---------------------------------------------------------------------------
# balance_low rule
# ---------------------------------------------------------------------------


def test_balance_low_trigger_duplicate_recovery_and_cross_day(conn, hermes_home):
    set_threshold(hermes_home, balance_low=5.0)  # 5 CNY → 5e8 units

    fired = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=int(4.0 * 1e8), now=DAY1,
    )
    assert fired["action"] == "fired"
    rows = notif_rows(conn)
    assert len(rows) == 1
    assert rows[0]["kind"] == "balance_low"
    assert rows[0]["rank"] == notifications.RANK_BALANCE_LOW
    assert rows[0]["dedup_key"] == f"balance_low:fp1:{DAY1_KEY}"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["observed_balance_units"] == int(4.0 * 1e8)
    assert payload["balance_low_threshold_units"] == int(5.0 * 1e8)
    assert payload["currency"] == "CNY"

    # same observation replayed (restart/replay) → duplicate, never a second row
    again = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=int(4.0 * 1e8), now=DAY1 + 1000,
    )
    assert again["action"] == "duplicate"
    assert len(notif_rows(conn)) == 1

    # recovery (≥ threshold) → standing notification auto-dismissed
    cleared = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=int(5.0 * 1e8), now=DAY1 + 2000,
    )
    assert cleared["action"] == "cleared"
    assert notifications.pending(conn, now=DAY1 + 2000) == []

    # re-dip within the same day stays silent (persistent dedup outranks re-ring)
    redip = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=int(1.0 * 1e8), now=DAY1 + 3000,
    )
    assert redip["action"] == "duplicate"
    assert len(notif_rows(conn)) == 1

    # next local day re-arms the key (跨日重置)
    next_day = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=int(4.0 * 1e8), now=DAY2,
    )
    assert next_day["action"] == "fired"
    assert {r["dedup_key"] for r in notif_rows(conn)} == {
        f"balance_low:fp1:{DAY1_KEY}", f"balance_low:fp1:{DAY2_KEY}",
    }


def test_balance_low_skips_when_threshold_unset_or_disabled(conn, hermes_home):
    # default config: thresholds.balance_low is None (null ≠ 0) → rule off
    result = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=0, now=DAY1,
    )
    assert result["action"] == "skipped"
    assert result["reason"] == "threshold_unset"
    assert notif_rows(conn) == []

    set_threshold(hermes_home, balance_low=5.0)
    config.save_config({"reminders": {"balance_low_enabled": False}}, home=hermes_home)
    result = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=1, now=DAY1,
    )
    assert result == {"action": "skipped", "reason": "disabled"}
    assert notif_rows(conn) == []


def test_balance_low_bad_threshold_degrades_to_off(conn, hermes_home):
    set_threshold(hermes_home, balance_low="not-a-number")
    result = rules.evaluate_balance_low(
        conn, scope="fp1", currency="CNY", observed_balance_units=1, now=DAY1,
    )
    assert result["action"] == "skipped"  # misconfig never fabricates a ring


def test_balance_low_hook_via_record_snapshot(conn, hermes_home):
    """The minimal hook at the end of balance_ledger.record_snapshot."""
    from whale_core import balance_ledger

    set_threshold(hermes_home, balance_low=5.0)
    kwargs = dict(
        provider_id="deepseek", scope="fp1", currency="CNY",
        granted_units=None, topped_up_units=None, raw={"total": "4.00"},
    )
    result = balance_ledger.record_snapshot(conn, observed_balance_units=int(4.0 * 1e8), fetched_at=DAY1, **kwargs)
    # hook must not change the return contract
    assert set(result) == {"inserted", "day", "spend_delta_units", "credit_delta_units", "gap_seconds", "partial"}
    assert result["inserted"] is True
    assert [r["kind"] for r in notif_rows(conn)] == ["balance_low"]

    # recovery snapshot dismisses the notification
    balance_ledger.record_snapshot(conn, observed_balance_units=int(9.0 * 1e8), fetched_at=DAY1 + 1000, **kwargs)
    assert notifications.pending(conn, now=DAY1 + 2000) == []


# ---------------------------------------------------------------------------
# daily budget rule
# ---------------------------------------------------------------------------


def _seed_usage_day(conn, scope, day, units, currency="CNY"):
    conn.execute(
        """
        INSERT INTO daily_summary(scope, day, track, currency, estimated_cost_units, tokens_json,
                                  partial, needs_review, updated_at)
        VALUES (?, ?, 'usage', ?, ?, '{}', 0, 0, ?)
        ON CONFLICT(scope, day, track) DO UPDATE SET estimated_cost_units=excluded.estimated_cost_units
        """,
        (scope, day, currency, units, DAY1),
    )
    conn.commit()


def test_daily_budget_fires_per_scope_never_merges_currencies(conn, hermes_home):
    set_threshold(hermes_home, daily_budget=10.0)
    _seed_usage_day(conn, "usage:default:CNY", DAY1_KEY, int(12.0 * 1e8), currency="CNY")
    _seed_usage_day(conn, "usage:default:USD", DAY1_KEY, int(2.0 * 1e8), currency="USD")
    _seed_usage_day(conn, "usage:default:none", DAY1_KEY, None, currency="none")  # unpriced bucket

    result = rules.evaluate_daily_budget(conn, now=DAY1)
    fired = result["fired"]
    assert len(fired) == 1
    assert fired[0]["scope"] == "usage:default:CNY"
    assert fired[0]["status"] == "fired"

    rows = notif_rows(conn)
    assert rows[0]["kind"] == "budget"
    assert rows[0]["rank"] == notifications.RANK_BUDGET
    assert rows[0]["dedup_key"] == f"budget:usage:default:CNY:{DAY1_KEY}"
    payload = json.loads(rows[0]["payload_json"])
    assert payload["estimated_cost_units"] == int(12.0 * 1e8)
    assert payload["daily_budget_units"] == int(10.0 * 1e8)
    assert payload["currency"] == "CNY"

    # same-day re-evaluation → duplicate (persistent dedup)
    assert rules.evaluate_daily_budget(conn, now=DAY1 + 1000)["fired"][0]["status"] == "duplicate"
    assert len(notif_rows(conn)) == 1

    # next day, nothing over budget → no new row (跨日重置 opens a fresh ledger)
    _seed_usage_day(conn, "usage:default:CNY", DAY2_KEY, int(1.0 * 1e8), currency="CNY")
    assert rules.evaluate_daily_budget(conn, now=DAY2)["fired"] == []
    assert len(notif_rows(conn)) == 1


def test_daily_budget_unset_or_disabled_never_fires(conn, hermes_home):
    _seed_usage_day(conn, "usage:default:CNY", DAY1_KEY, int(999.0 * 1e8), currency="CNY")
    assert rules.evaluate_daily_budget(conn, now=DAY1)["reason"] == "threshold_unset"
    config.save_config(
        {"thresholds": {"daily_budget": 10.0}, "reminders": {"budget_enabled": False}},
        home=hermes_home,
    )
    assert rules.evaluate_daily_budget(conn, now=DAY1) == {"action": "skipped", "reason": "disabled", "fired": []}
    assert notif_rows(conn) == []


def test_budget_fires_via_ingest_hook_and_resets_cross_day(client, hermes_home, pinned_clock):
    """End-to-end: settlement hook evaluates the budget; day key re-arms it."""
    set_threshold(hermes_home, daily_budget=10.0)
    pinned_clock["now"] = DAY1

    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(session_id="s1", cost_usd=11.0))
    assert res.status_code == 200
    conn = runtime_conn()
    rows = [r for r in notif_rows(conn) if r["kind"] == "budget"]
    assert len(rows) == 1
    assert rows[0]["dedup_key"].startswith("budget:usage:default:USD:2026-")

    # same day again → duplicate
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(session_id="s2", cost_usd=12.0))
    assert len([r for r in notif_rows(conn) if r["kind"] == "budget"]) == 1

    # next local day → fresh ring
    pinned_clock["now"] = DAY2
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(session_id="s3", cost_usd=13.0, received_at=DAY2))
    keys = {r["dedup_key"] for r in notif_rows(runtime_conn()) if r["kind"] == "budget"}
    assert len(keys) == 2


# ---------------------------------------------------------------------------
# turn_cost rule
# ---------------------------------------------------------------------------


def test_turn_cost_notification_with_ttl_and_dedup(conn, hermes_home):
    result = rules.evaluate_turn_cost(
        conn, dedup_key="D" * 40, estimated_cost_units=50_000_000,
        currency="CNY", model="deepseek-chat", cost_basis="hermes_estimate", now=DAY1,
    )
    assert result["action"] == "fired"
    rows = notif_rows(conn)
    assert rows[0]["kind"] == "turn_cost"
    assert rows[0]["rank"] == notifications.RANK_TURN_COST
    assert rows[0]["dedup_key"] == f"turn:{'D' * 40}"
    assert rows[0]["ttl_ms"] == 5000  # config bubbles.turn_cost_ttl_ms default
    payload = json.loads(rows[0]["payload_json"])
    assert payload["estimated_cost_units"] == 50_000_000

    # replay of the same turn → same dedup → duplicate (restart/replay safe)
    again = rules.evaluate_turn_cost(
        conn, dedup_key="D" * 40, estimated_cost_units=50_000_000,
        currency="CNY", model="deepseek-chat", cost_basis="hermes_estimate", now=DAY1,
    )
    assert again["action"] == "duplicate"
    assert len(notif_rows(conn)) == 1


def test_turn_cost_disabled_floor_and_unpriced(conn, hermes_home):
    # unpriced turn → nothing honest to show
    assert rules.evaluate_turn_cost(
        conn, dedup_key="k1", estimated_cost_units=None, currency=None, now=DAY1,
    )["action"] == "skipped"

    set_threshold(hermes_home, turn_cost_min=0.01)  # 1e6 units floor
    below = rules.evaluate_turn_cost(
        conn, dedup_key="k2", estimated_cost_units=999_999, currency="CNY", now=DAY1,
    )
    assert below["action"] == "skipped"
    assert below["reason"] == "below_floor"
    above = rules.evaluate_turn_cost(
        conn, dedup_key="k3", estimated_cost_units=1_000_000, currency="CNY", now=DAY1,
    )
    assert above["action"] == "fired"

    config.save_config({"reminders": {"turn_cost_enabled": False}}, home=hermes_home)
    assert rules.evaluate_turn_cost(
        conn, dedup_key="k4", estimated_cost_units=1_000_000, currency="CNY", now=DAY1,
    )["action"] == "skipped"
    assert len(notif_rows(conn)) == 1


# ---------------------------------------------------------------------------
# ingest hook: settled contract + rules isolation + restart (DR-14)
# ---------------------------------------------------------------------------


def test_ingest_settled_contract_exact_fields_and_old_fields(client):
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(cost_usd=0.5))
    assert res.status_code == 200
    body = res.json()
    # old fields preserved
    assert body["status"] == "accepted"
    assert body["accepted"] == 1
    assert body["duplicate"] == 0
    assert body["aligned"] is False
    # new field: exact key set, exact names (cross-package contract)
    assert len(body["settled"]) == 1
    assert set(body["settled"][0]) == {"dedup_key", "estimated_cost_units", "currency", "cost_basis"}
    assert body["settled"][0]["estimated_cost_units"] == 50_000_000
    assert body["settled"][0]["currency"] == "USD"
    assert body["settled"][0]["cost_basis"] == "hermes_estimate"
    # dedup_key matches the ledger row
    row = runtime_conn().execute("SELECT dedup_key FROM turn_cost").fetchone()
    assert body["settled"][0]["dedup_key"] == row["dedup_key"]


def test_ingest_settled_null_for_unpriced_turn(client):
    payload = make_turn(model="mystery-model-xyz", cost_usd=None)
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload)
    body = res.json()
    assert body["settled"][0]["estimated_cost_units"] is None  # honest null, never 0
    assert body["settled"][0]["currency"] is None
    assert body["settled"][0]["cost_basis"] == "token_only"


def test_ingest_duplicate_and_aligned_responses_keep_old_shape(client):
    payload = make_turn(cost_usd=0.25)
    assert client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload).json()["settled"]
    dup = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload).json()
    assert dup == {"status": "duplicate", "accepted": 0, "duplicate": 1, "aligned": False}
    assert "settled" not in dup

    aligned_payload = make_turn(session_id="s-align", cost_usd=1.0, after_reconnect=True)
    aligned = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=aligned_payload).json()
    assert aligned == {"status": "accepted", "accepted": 0, "duplicate": 0, "aligned": True}
    assert "settled" not in aligned

    skipped_payload = make_turn(session_id="s-skip", cost_usd=1.0, usage={"input": None, "output": None})
    skipped = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=skipped_payload).json()
    assert "settled" not in skipped
    assert skipped.get("skipped") == 1


def test_ingest_batch_settled_only_accepted_turns(client):
    first = make_turn(session_id="b1", cost_usd=0.10)
    second = make_turn(session_id="b2", cost_usd=0.20)
    assert client.post(f"{MOUNT_PREFIX}/ingest/turn", json={"turns": [first, second]}).json()["settled"]

    mixed = {"turns": [make_turn(session_id="b3", cost_usd=0.30), first]}  # second is a duplicate
    body = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=mixed).json()
    assert body["accepted"] == 1
    assert body["duplicate"] == 1
    assert len(body["settled"]) == 1
    assert body["settled"][0]["estimated_cost_units"] == 30_000_000


def test_turn_settlement_fires_one_turn_cost_notification(client):
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(cost_usd=0.75))
    dedup = res.json()["settled"][0]["dedup_key"]
    rows = [r for r in notif_rows(runtime_conn()) if r["kind"] == "turn_cost"]
    assert len(rows) == 1
    assert rows[0]["dedup_key"] == f"turn:{dedup}"

    # replay the exact turn (restart/replay) → no second notification
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(cost_usd=0.75))
    assert len([r for r in notif_rows(runtime_conn()) if r["kind"] == "turn_cost"]) == 1


def test_restart_replay_does_not_re_ring(client):
    """DR-14: a fresh runtime handle (process restart simulation) replays the
    same batch → duplicate settlement, notification count unchanged."""
    payload = make_turn(session_id="restart-1", cost_usd=1.5)
    first = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload).json()
    assert first["accepted"] == 1

    from whale_core import api as whale_api

    whale_api.reset_runtime()  # close the db handle; next request rebuilds it
    second = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload).json()
    assert second["status"] == "duplicate"
    assert "settled" not in second
    rows = notif_rows(runtime_conn())
    assert len([r for r in rows if r["kind"] == "turn_cost"]) == 1


def test_rules_crash_never_breaks_settlement(client, monkeypatch):
    """Hook isolation: a raising rule must not change the return value or the
    ledger transaction (reminders are strictly best-effort)."""
    from whale_core import rules as whale_rules

    def boom(*args, **kwargs):
        raise RuntimeError("rules exploded")

    monkeypatch.setattr(whale_rules, "evaluate_turn_cost", boom)
    monkeypatch.setattr(whale_rules, "evaluate_daily_budget", boom)
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(cost_usd=0.5))
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["settled"][0]["estimated_cost_units"] == 50_000_000
    conn = runtime_conn()
    assert conn.execute("SELECT COUNT(*) FROM usage_event").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM turn_cost").fetchone()[0] == 1


def test_rules_crash_never_breaks_snapshot(conn, hermes_home, monkeypatch):
    from whale_core import balance_ledger
    from whale_core import rules as whale_rules

    def boom(*args, **kwargs):
        raise RuntimeError("rules exploded")

    monkeypatch.setattr(whale_rules, "evaluate_balance_low", boom)
    set_threshold(hermes_home, balance_low=5.0)
    result = balance_ledger.record_snapshot(
        conn, provider_id="deepseek", scope="fp1", currency="CNY",
        observed_balance_units=int(1.0 * 1e8), granted_units=None, topped_up_units=None,
        raw={"total": "1.00"}, fetched_at=DAY1,
    )
    assert result["inserted"] is True  # booking chain unaffected
    assert conn.execute("SELECT COUNT(*) FROM balance_snapshot").fetchone()[0] == 1


# ---------------------------------------------------------------------------
# REST naming lint over the M8 surfaces (DATA_MODEL §8.1)
# ---------------------------------------------------------------------------


def test_rest_naming_lint_over_new_surfaces(client, hermes_home):
    set_threshold(hermes_home, balance_low=5.0)
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(cost_usd=0.5))

    ingest_body = client.post(
        f"{MOUNT_PREFIX}/ingest/turn", json=make_turn(session_id="lint-1", cost_usd=0.6)
    ).json()
    assert find_bare_money_keys(ingest_body) == []

    wait_state = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert find_bare_money_keys(wait_state) == []

    for row in notif_rows(runtime_conn()):
        assert find_bare_money_keys(json.loads(row["payload_json"])) == []


# ---------------------------------------------------------------------------
# config default (minimal M8 addition)
# ---------------------------------------------------------------------------


def test_thresholds_default_includes_turn_cost_min(client):
    body = client.get(f"{MOUNT_PREFIX}/config").json()
    assert body["thresholds"]["turn_cost_min"] is None
    assert config.DEFAULTS["thresholds"]["turn_cost_min"] is None
