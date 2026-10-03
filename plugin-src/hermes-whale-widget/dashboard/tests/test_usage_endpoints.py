"""CON-02/CON-03 — /usage/summary + /usage/turns: schema, null ≠ 0 semantics,
per-model grouping, and the standing REST naming lint (DATA_MODEL §8.1)."""

from __future__ import annotations

import pytest

from conftest import MOUNT_PREFIX
from whale_core.security import find_bare_money_keys

BASE_MS = 1_792_000_000_000


def _turn(session_id="s1", *, received_at=None, model="deepseek-chat", status="complete", **usage):
    return {
        "session_id": session_id,
        "profile": "default",
        "model": model,
        "usage": usage or {"input": 100, "output": 50, "calls": 3},
        "received_at": received_at if received_at is not None else BASE_MS,
        "status": status,
    }


@pytest.fixture(autouse=True)
def _pin_clock():
    from whale_core import clock

    clock.set_clock(lambda: BASE_MS / 1000.0)
    yield
    clock.reset_clock()


def _seed(client):
    # session-cumulative snapshots must GROW between turns (delta accounting)
    client.post(
        f"{MOUNT_PREFIX}/ingest/turn",
        json=_turn(model="deepseek-chat", input=100, output=50, calls=3),
    )
    client.post(
        f"{MOUNT_PREFIX}/ingest/turn",
        json=_turn(received_at=BASE_MS + 60_000, model="deepseek-reasoner", input=130, output=120),
    )


def test_empty_summary_null_semantics(client):
    res = client.get(f"{MOUNT_PREFIX}/usage/summary")
    assert res.status_code == 200
    body = res.json()
    # null ≠ 0: no turns → no estimate AND no fabricated zero claim
    assert body["estimated_today_units"] is None
    assert body["estimated_today_basis"] is None
    assert body["turns_today"] == 0
    assert body["per_model"] == []
    assert len(body["estimated_days"]) == 7
    assert body["estimated_days"][-1]["day"] == body["day"]
    assert find_bare_money_keys(body) == []


def test_summary_after_two_turns_two_models(client):
    _seed(client)
    body = client.get(f"{MOUNT_PREFIX}/usage/summary").json()
    assert body["turns_today"] == 2
    # M3 pricing: both turns priced from the builtin CNY table
    # (chat 100×2+50×8=60_000; reasoner deltas 30×6+70×24=186_000)
    assert body["estimated_today_units"] == 246_000
    assert body["estimated_today_basis"] == "whale_pricing"
    assert body["tokens_today"]["input"] == 130
    assert body["tokens_today"]["output"] == 120
    assert body["tokens_today"]["calls"] == 3  # turn2 calls == turn1 calls → zero delta

    models = {m["model"]: m for m in body["per_model"]}
    assert set(models) == {"deepseek-chat", "deepseek-reasoner"}
    assert models["deepseek-chat"]["turns"] == 1 and models["deepseek-chat"]["input"] == 100
    assert models["deepseek-reasoner"]["output"] == 70
    assert find_bare_money_keys(body) == []


def test_summary_days7_includes_today_and_partial_flags(client):
    _seed(client)
    body = client.get(f"{MOUNT_PREFIX}/usage/summary?days=7").json()
    assert len(body["estimated_days"]) == 7
    today = body["estimated_days"][-1]
    assert today["tokens"]["input"] == 130
    assert today["estimated_cost_units"] == 246_000  # priced turns roll up
    assert body["partial_flags"]["provisional_turns"] == 0


def test_summary_rejects_bad_days(client):
    assert client.get(f"{MOUNT_PREFIX}/usage/summary?days=0").status_code == 400
    assert client.get(f"{MOUNT_PREFIX}/usage/summary?days=400").status_code == 400


def test_turns_listing_order_shape_and_null_cost(client):
    _seed(client)
    body = client.get(f"{MOUNT_PREFIX}/usage/turns").json()
    assert body["count"] == 2 and body["limit"] == 20
    seqs = [t["turn_seq"] for t in body["turns"]]
    assert seqs == [2, 1]  # most recent first
    first = body["turns"][0]
    assert first["model"] == "deepseek-reasoner"
    assert first["cost_basis"] == "whale_pricing"
    assert first["estimated_cost_units"] == 186_000  # 30×6 + 70×24 CNY-e8
    assert first["currency"] == "CNY"
    assert first["tokens"]["input"] == 30
    assert find_bare_money_keys(body) == []


def test_turns_session_filter_and_limit(client):
    _seed(client)
    client.post(
        f"{MOUNT_PREFIX}/ingest/turn",
        json=_turn(session_id="other", received_at=BASE_MS + 120_000, input=5),
    )
    only = client.get(f"{MOUNT_PREFIX}/usage/turns", params={"session_id": "other"}).json()
    assert only["count"] == 1
    assert only["turns"][0]["session_id"] == "other"

    limited = client.get(f"{MOUNT_PREFIX}/usage/turns", params={"limit": 1}).json()
    assert limited["count"] == 1 and limited["limit"] == 1
    assert client.get(f"{MOUNT_PREFIX}/usage/turns", params={"limit": 0}).status_code == 400
    assert client.get(f"{MOUNT_PREFIX}/usage/turns", params={"limit": 999}).status_code == 400


def test_provisional_turns_surface_in_partial_flags(client):
    client.post(
        f"{MOUNT_PREFIX}/ingest/turn",
        json=_turn(received_at=BASE_MS, status="interrupted", input=10),
    )
    body = client.get(f"{MOUNT_PREFIX}/usage/summary").json()
    assert body["partial_flags"]["provisional_turns"] == 1
