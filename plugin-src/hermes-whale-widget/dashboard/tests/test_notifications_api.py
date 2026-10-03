"""Goal-pass P0-2 — /notifications consumer endpoint contract (REM chain closure).

End-to-end: rules fire → GET /notifications → POST /notifications/dismiss.
"""

from __future__ import annotations

import pytest

from conftest import MOUNT_PREFIX
from whale_core import clock, notifications, rules
from whale_core.db import connect as db_connect
from whale_core.migrations import migrate
from whale_core.security import find_bare_money_keys

BASE_MS = 1_792_000_000_000
SCALE = 100_000_000


@pytest.fixture(autouse=True)
def _pin_clock():
    clock.set_clock(lambda: BASE_MS / 1000.0)
    yield
    clock.reset_clock()


def _turn(**usage):
    return {
        "session_id": "s1",
        "profile": "default",
        "model": "deepseek-chat",
        "usage": usage,
        "received_at": BASE_MS,
        "status": "complete",
    }


def test_ingest_settled_turn_fires_turn_cost_notification(client, hermes_home):
    """Full chain: turn cost ≥ configured floor → notification row → REST view."""
    client.put(
        f"{MOUNT_PREFIX}/config",
        json={"thresholds": {"turn_cost_min": 0.000001}, "reminders": {"turn_cost_enabled": True}},
    )
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=_turn(input=100_000, output=100_000))
    assert res.status_code == 200
    body = res.json()
    assert isinstance(body.get("settled"), list) and body["settled"], body

    listing = client.get(f"{MOUNT_PREFIX}/notifications").json()
    assert find_bare_money_keys(listing) == []
    kinds = [n["kind"] for n in listing["notifications"]]
    assert "turn_cost" in kinds
    item = next(n for n in listing["notifications"] if n["kind"] == "turn_cost")
    assert item["rank"] == 3
    assert item["dedup_key"] in listing["fired_dedup_keys"]
    # payload names carry the §8.1 class prefixes
    assert "estimated_cost_units" in item["payload"]


def test_repeated_ingest_does_not_duplicate_notification(client):
    client.put(
        f"{MOUNT_PREFIX}/config",
        json={"thresholds": {"turn_cost_min": 0.000001}},
    )
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=_turn(input=100_000, output=100_000))
    listing = client.get(f"{MOUNT_PREFIX}/notifications").json()
    turn_keys = [n["dedup_key"] for n in listing["notifications"] if n["kind"] == "turn_cost"]
    assert len(turn_keys) == 1


def test_dismiss_roundtrip(client):
    res = client.post(f"{MOUNT_PREFIX}/notifications/dismiss", json={"dedup_key": "nope"})
    assert res.status_code == 404

    conn = db_connect(_whale_db())
    migrate(conn)
    notifications.fire(
        conn, kind="budget", rank=1, dedup_key="budget:x", payload={"day": "d"}, ttl_ms=0,
        now=clock.now_ms(),
    )
    conn.close()

    res = client.post(f"{MOUNT_PREFIX}/notifications/dismiss", json={"dedup_key": "budget:x"})
    assert res.status_code == 200 and res.json()["dismissed"] is True
    assert client.post(f"{MOUNT_PREFIX}/notifications/dismiss", json={"dedup_key": "budget:x"}).status_code == 404
    assert client.get(f"{MOUNT_PREFIX}/notifications").json()["notifications"] == []


def test_dismiss_validation_and_loopback(client_strict_loopback):
    assert client_strict_loopback.post(
        f"{MOUNT_PREFIX}/notifications/dismiss", json={"dedup_key": "x"}
    ).status_code == 403
    assert client_strict_loopback.get(f"{MOUNT_PREFIX}/notifications").status_code == 200


def _whale_db():
    from whale_core import config as whale_config

    return whale_config.data_dir() / "whale.db"
