"""WP-e2e — Python-side end-to-end user-flow tests (Level 3 integration +
Level 4 user-flow simulation).

Four scenarios, each one complete user journey from the config entry point to
the final observable result. Nothing in the chains under test is mocked: the
REST routes, idempotent settlement, pricing, the rules engine, the persistent
notification store, the wait bridge and the queries all run for real. The only
injected seams are the sanctioned ones:

* the clock — ``whale_core.clock.set_clock`` (TEST_PLAN §2.3, conftest
  convention: each test manages its own pinned clock);
* the outbound HTTP transport for the balance flow — ``httpx.MockTransport``
  injected at the ``whale_core.balance_ledger.refresh_balance`` ledger layer
  (the REST layer cannot inject a transport; TEST_PLAN §2.1 pins this seam and
  forbids real paid APIs).

The direct ``whale_api._ensure_runtime().conn`` handle used in the balance
flow shares the very same ``whale.db`` (WAL, multi-connection readable) as the
TestClient, so whale_core-layer writes stay observable through the REST door.

Expected money figures are exact 1e8 fixed-point values, derived from
``whale_core.pricing.compute_settlement`` with the builtin deepseek-chat quote
(miss=2 / hit=0.04 / out=8 CNY per 1M tokens; reasoning ⊆ output; DeepSeek
bills no cache writes):

    numerator = input×miss + cache_read×hit + output×out   (units·tokens space)
              = 100_000 × 200_000_000 + 0 × 4_000_000 + 50_000 × 800_000_000
              = 6.0e13
    units     = 6.0e13 // 1_000_000 = 60_000_000   (= 0.60000000 CNY)

Run: .venv/Scripts/python.exe -m pytest tests/test_e2e_flow.py -q --basetemp=.pytest-tmp-e
"""

from __future__ import annotations

import httpx
import pytest

from conftest import MOUNT_PREFIX
from whale_core import api as whale_api
from whale_core import balance_ledger, clock, ingest, notifications, pricing
from whale_core.providers import gateway

BASE_MS = 1_792_000_000_000  # arbitrary fixed epoch ms; day keys derived per local tz
DAY_MS = 86_400_000
UNIT = pricing.SCALE  # 1e8 fixed point — exact money assertions below
FAKE_KEY = "sk-test-fake-deepseek-e2e-00000001"  # sanctioned test prefix, TEST_PLAN §2.1


@pytest.fixture(autouse=True)
def pinned_clock():
    """Injectable clock (TEST_PLAN §2.3) — a state dict drives ``now_ms``.

    Scenarios that need to advance time (balance dip/recovery, cross-day
    budget reset) mutate ``state["now"]``; the others stay pinned at BASE_MS.
    """
    state = {"now": BASE_MS}
    clock.set_clock(lambda: state["now"] / 1000.0)
    yield state
    clock.reset_clock()


def _turn(session_id="e2e-s1", *, received_at=None, model="deepseek-chat", profile="default", **usage):
    return {
        "session_id": session_id,
        "profile": profile,
        "model": model,
        "usage": usage,
        "received_at": received_at if received_at is not None else BASE_MS,
        "status": "complete",
    }


def _notifications(client):
    return client.get(f"{MOUNT_PREFIX}/notifications").json()


# ---------------------------------------------------------------------------
# Scenario 1 — bookkeeping main flow: config → settle → queries → ring → dismiss
# ---------------------------------------------------------------------------


def test_e2e_bookkeeping_flow_from_config_to_dismissed_notification(client):
    """PUT turn_cost_min → POST /ingest/turn (settled) → /usage/turns +
    /usage/summary agree → turn_cost notification rings → dismiss → gone;
    a replayed turn stays duplicate and never re-rings."""
    # 1. the user sets the per-turn notification floor through the config door
    res = client.put(f"{MOUNT_PREFIX}/config", json={"thresholds": {"turn_cost_min": 0.000001}})
    assert res.status_code == 200
    assert res.json()["thresholds"]["turn_cost_min"] == 0.000001  # = 100 units

    # 2. one turn settles: deepseek-chat, 100k in / 50k out / 0 cache-read
    #    → exactly 60_000_000 units (0.60000000 CNY, see module docstring)
    turn = _turn(input=100_000, output=50_000, cache_read=0)
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=turn)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["accepted"] == 1 and body["duplicate"] == 0 and body["aligned"] is False
    assert len(body["settled"]) == 1
    settled = body["settled"][0]
    assert set(settled) == {"dedup_key", "estimated_cost_units", "currency", "cost_basis"}
    assert settled["estimated_cost_units"] == 60_000_000
    assert settled["currency"] == "CNY"
    assert settled["cost_basis"] == "whale_pricing"
    dedup = settled["dedup_key"]
    assert isinstance(dedup, str) and len(dedup) == 40

    # 3. the settled turn is visible in /usage/turns with the same money
    turns = client.get(f"{MOUNT_PREFIX}/usage/turns").json()["turns"]
    assert len(turns) == 1
    row = turns[0]
    assert row["dedup_key"] == dedup
    assert row["model"] == "deepseek-chat"
    assert row["day"] == ingest.local_day_key(BASE_MS)
    assert row["cost_basis"] == "whale_pricing"
    assert row["estimated_cost_units"] == 60_000_000
    assert row["currency"] == "CNY"
    assert row["tokens"]["input"] == 100_000
    assert row["tokens"]["output"] == 50_000
    assert row["tokens"]["cache_read"] == 0

    # 4. /usage/summary rolls the same settlement into today's total
    summary = client.get(f"{MOUNT_PREFIX}/usage/summary").json()
    assert summary["estimated_today_units"] == 60_000_000
    assert summary["estimated_today_currency"] == "CNY"
    assert summary["estimated_today_basis"] == "whale_pricing"
    assert summary["turns_today"] == 1
    cny = next(b for b in summary["estimated_today_by_currency"] if b["currency"] == "CNY")
    assert cny["estimated_cost_units"] == 60_000_000
    assert cny["priced_turns"] == 1

    # 5. the turn_cost reminder fired once, deduped by the turn's own key
    listing = _notifications(client)
    rings = [n for n in listing["notifications"] if n["kind"] == "turn_cost"]
    assert [n["dedup_key"] for n in rings] == [f"turn:{dedup}"]
    assert rings[0]["rank"] == notifications.RANK_TURN_COST
    assert rings[0]["ttl_ms"] == 5000  # config bubbles.turn_cost_ttl_ms default
    assert rings[0]["payload"]["estimated_cost_units"] == 60_000_000
    assert rings[0]["payload"]["currency"] == "CNY"
    assert rings[0]["payload"]["model"] == "deepseek-chat"
    assert f"turn:{dedup}" in listing["fired_dedup_keys"]

    # 6. replaying the same turn → duplicate, settled exactly once → rings once
    dup = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=turn)
    assert dup.status_code == 200
    assert dup.json() == {"status": "duplicate", "accepted": 0, "duplicate": 1, "aligned": False}
    listing = _notifications(client)
    assert [n["dedup_key"] for n in listing["notifications"] if n["kind"] == "turn_cost"] == [f"turn:{dedup}"]

    # 7. the user dismisses the ring → it disappears from the consumer view
    res = client.post(f"{MOUNT_PREFIX}/notifications/dismiss", json={"dedup_key": f"turn:{dedup}"})
    assert res.status_code == 200
    assert res.json() == {"dedup_key": f"turn:{dedup}", "dismissed": True}
    listing = _notifications(client)
    assert all(n["kind"] != "turn_cost" for n in listing["notifications"])
    assert f"turn:{dedup}" not in listing["fired_dedup_keys"]


# ---------------------------------------------------------------------------
# Scenario 2 — balance low flow: credential + threshold → dip fires (ttl 0)
#              → recovery auto-dismisses
# ---------------------------------------------------------------------------


def test_e2e_balance_low_flow_from_config_to_recovery(client, pinned_clock, monkeypatch):
    """PUT balance_low=100 → whale_core-layer refresh (MockTransport; the REST
    layer cannot inject a transport): 110 no alert → 90 fires the standing
    balance_low ring → 110 recovers and the ring is auto-dismissed. The direct
    conn shares the runtime whale.db with the client."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    res = client.put(f"{MOUNT_PREFIX}/config", json={"thresholds": {"balance_low": 100}})
    assert res.status_code == 200
    assert res.json()["thresholds"]["balance_low"] == 100  # = 100 × 1e8 units

    conn = whale_api._ensure_runtime().conn  # same whale.db the TestClient uses

    def refresh(total: str):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url == "https://api.deepseek.com/user/balance"
            assert request.headers.get("Authorization") == f"Bearer {FAKE_KEY}"
            return httpx.Response(
                200,
                json={"is_available": True,
                      "balance_infos": [{"currency": "CNY", "total_balance": total}]},
            )

        return balance_ledger.refresh_balance(conn, transport=httpx.MockTransport(handler))

    # 1. 110.00 ≥ 100 → no warning
    state = refresh("110.00")
    assert state["state"] == "ok"
    assert state["observed_balance_units"] == 110 * UNIT
    listing = _notifications(client)
    assert listing["notifications"] == []

    # 2. clock advances; balance dips to 90.00 < 100 → standing low-balance ring
    pinned_clock["now"] = BASE_MS + 2000
    state = refresh("90.00")
    assert state["state"] == "ok"
    assert state["observed_balance_units"] == 90 * UNIT

    listing = _notifications(client)
    lows = [n for n in listing["notifications"] if n["kind"] == "balance_low"]
    assert len(lows) == 1
    low = lows[0]
    scope = gateway.fingerprint(FAKE_KEY)  # dedup scope = credential fingerprint
    day = ingest.local_day_key(BASE_MS + 2000)
    assert low["dedup_key"] == f"balance_low:{scope}:{day}"
    assert low["rank"] == notifications.RANK_BALANCE_LOW
    assert low["ttl_ms"] == 0  # 常驻预警泡 — persistent until recovery
    assert low["payload"]["observed_balance_units"] == 90 * UNIT
    assert low["payload"]["balance_low_threshold_units"] == 100 * UNIT
    assert low["payload"]["currency"] == "CNY"
    assert low["dedup_key"] in listing["fired_dedup_keys"]

    # 3. balance recovers to 110.00 ≥ threshold → the standing ring auto-clears
    pinned_clock["now"] = BASE_MS + 4000
    state = refresh("110.00")
    assert state["state"] == "ok"
    assert state["observed_balance_units"] == 110 * UNIT

    listing = _notifications(client)
    assert listing["notifications"] == []
    assert listing["fired_dedup_keys"] == []

    # 4. the ledger-layer writes are visible through the REST door (shared db)
    balance_view = client.get(f"{MOUNT_PREFIX}/balance").json()
    assert balance_view["state"] == "ok"
    assert balance_view["observed_balance_units"] == 110 * UNIT
    assert FAKE_KEY not in str(balance_view)  # the credential never leaves the half


# ---------------------------------------------------------------------------
# Scenario 3 — question wait flow: open → slot + wait ring → close → cleared;
#              malformed payloads and non-loopback writers are refused
# ---------------------------------------------------------------------------


def test_e2e_question_wait_flow_from_open_to_close(client, client_strict_loopback):
    open_event = {"kind": "question", "phase": "open", "tool_id": "t1", "session_id": "s1"}
    close_event = {"kind": "question", "phase": "close", "tool_id": "t1", "session_id": "s1"}

    # 1. a question opens → slot recorded + persistent wait notification fired
    res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=open_event)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["phase"] == "open"
    assert body["slot"]["tool_id"] == "t1"
    assert body["slot"]["session_id"] == "s1"
    assert body["slot"]["since"] == BASE_MS
    assert body["notification"] == "fired"

    # 2. GET /wait-state shows the slot and the wait dedup key
    state = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert set(state) == {"question_slots", "approval_slots", "fired_dedup_keys"}
    slots = {slot["tool_id"]: slot for slot in state["question_slots"]}
    assert set(slots) == {"t1"}
    assert slots["t1"]["session_id"] == "s1"
    assert slots["t1"]["since"] == BASE_MS
    assert "wait:question:t1" in state["fired_dedup_keys"]

    # the same standing reminder is visible on the notifications surface
    listing = _notifications(client)
    waits = [n for n in listing["notifications"] if n["kind"] == "wait_input"]
    assert [n["dedup_key"] for n in waits] == ["wait:question:t1"]
    assert waits[0]["ttl_ms"] == 0  # 常驻等待泡

    # 3. the question closes → slot cleared + ring dismissed
    res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=close_event)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["phase"] == "close"
    assert body["removed"] is True
    assert body["dismissed"] is True

    state = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert state["question_slots"] == []
    assert "wait:question:t1" not in state["fired_dedup_keys"]

    # 4. malformed payloads are refused before touching the ledger (400)
    for payload, snippet in (
        ({"kind": "approval", "phase": "open", "tool_id": "t1", "session_id": "s1"}, "kind"),
        ({"kind": "question", "tool_id": "t1", "session_id": "s1"}, "phase"),
        ({"kind": "question", "phase": "open", "session_id": "s1"}, "tool_id"),
    ):
        res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=payload)
        assert res.status_code == 400
        assert snippet in res.json()["detail"]

    # 5. a non-loopback writer never gets past the guard (403)
    res = client_strict_loopback.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=open_event)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# Scenario 4 — daily budget flow: config → two turns cross the line → budget
#              ring (per-currency scope) → cross-day the dedup re-arms
# ---------------------------------------------------------------------------


def test_e2e_daily_budget_flow_from_config_to_cross_day_reset(client, pinned_clock):
    """PUT daily_budget=0.8 CNY → turn 1 (0.60) stays silent → turn 2 (+0.50)
    pushes today's CNY scope to 1.10 ≥ 0.8 → budget ring keyed per scope+day;
    after the clock crosses the local day the new turn books on the new day
    and never reuses yesterday's dedup (day 2 total 0.60 < 0.8 → no new ring)."""
    res = client.put(f"{MOUNT_PREFIX}/config", json={"thresholds": {"daily_budget": 0.8}})
    assert res.status_code == 200
    assert res.json()["thresholds"]["daily_budget"] == 0.8  # = 80_000_000 units

    day1 = ingest.local_day_key(BASE_MS)
    day2 = ingest.local_day_key(BASE_MS + DAY_MS)
    assert day1 != day2

    # 1. turn 1 → 0.60000000 CNY today: under budget, no ring
    t1 = _turn(session_id="e2e-budget", received_at=BASE_MS, input=100_000, output=50_000, cache_read=0)
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=t1)
    assert res.status_code == 200
    t1_dedup = res.json()["settled"][0]["dedup_key"]
    assert res.json()["settled"][0]["estimated_cost_units"] == 60_000_000
    assert all(n["kind"] != "budget" for n in _notifications(client)["notifications"])

    # 2. turn 2 (+0.50000000 CNY) → today's CNY scope reaches 1.10 ≥ 0.8 → ring
    t2 = _turn(session_id="e2e-budget", received_at=BASE_MS + 60_000,
               input=150_000, output=100_000, cache_read=0)  # cumulative: deltas 50k/50k
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=t2)
    assert res.status_code == 200
    t2_dedup = res.json()["settled"][0]["dedup_key"]
    assert res.json()["settled"][0]["estimated_cost_units"] == 50_000_000

    listing = _notifications(client)
    budgets = [n for n in listing["notifications"] if n["kind"] == "budget"]
    assert len(budgets) == 1
    budget = budgets[0]
    assert budget["dedup_key"] == f"budget:usage:default:CNY:{day1}"
    assert budget["rank"] == notifications.RANK_BUDGET
    assert budget["ttl_ms"] == 0
    assert budget["payload"]["estimated_cost_units"] == 110_000_000  # 0.60 + 0.50
    assert budget["payload"]["daily_budget_units"] == 80_000_000
    assert budget["payload"]["currency"] == "CNY"
    assert budget["payload"]["day"] == day1
    assert budget["dedup_key"] in listing["fired_dedup_keys"]

    # 3. the clock crosses into the next local day; a new turn books there
    pinned_clock["now"] = BASE_MS + DAY_MS
    t3 = _turn(session_id="e2e-budget-d2", received_at=BASE_MS + DAY_MS,
               input=100_000, output=50_000, cache_read=0)
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=t3)
    assert res.status_code == 200
    t3_dedup = res.json()["settled"][0]["dedup_key"]
    assert t3_dedup not in {t1_dedup, t2_dedup}
    assert res.json()["settled"][0]["estimated_cost_units"] == 60_000_000

    turns = client.get(f"{MOUNT_PREFIX}/usage/turns").json()["turns"]
    by_key = {t["dedup_key"]: t for t in turns}
    assert by_key[t3_dedup]["day"] == day2  # the new turn lives on the new day

    # 4. the new turn carries only its own dedup: day 2's CNY total (0.60) is
    #    under budget → no second budget ring; the standing ring is still
    #    yesterday's key (ttl 0), and day-1 turn rings have expired (ttl 5s)
    listing = _notifications(client)
    assert set(listing["fired_dedup_keys"]) == {
        f"budget:usage:default:CNY:{day1}",
        f"turn:{t3_dedup}",
    }
    conn = whale_api._ensure_runtime().conn
    budget_rows = [dict(r) for r in conn.execute(
        "SELECT dedup_key FROM notification WHERE kind = 'budget' ORDER BY id"
    ).fetchall()]
    assert [r["dedup_key"] for r in budget_rows] == [f"budget:usage:default:CNY:{day1}"]
