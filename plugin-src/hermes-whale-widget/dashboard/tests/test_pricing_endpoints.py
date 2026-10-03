"""M3 pricing surface — REST overview + custom overrides + settlement tie-in.

Naming lint (CON-03) runs on every payload: bare ``cost``/``spend``/``used``
keys may never leave the plugin (DATA_MODEL §8.1).
"""

from __future__ import annotations

import pytest

from conftest import MOUNT_PREFIX
from whale_core import api as whale_api, clock
from whale_core.ingest import ingest_turn
from whale_core.security import find_bare_money_keys

BASE_MS = 1_792_000_000_000

VALID_QUOTE = {"hit": "1", "miss": "2", "out": "8", "currency": "CNY"}


@pytest.fixture(autouse=True)
def _pin_clock():
    clock.set_clock(lambda: BASE_MS / 1000.0)
    yield
    clock.reset_clock()


def _turn(model="my-custom-model", **usage):
    return {
        "session_id": "s1",
        "profile": "default",
        "model": model,
        "usage": usage or {"input": 1_000_000, "output": 1_000_000, "cache_read": 0, "cache_write": 0},
        "received_at": BASE_MS,
        "status": "complete",
    }


def test_pricing_overview_shape_and_naming_lint(client):
    res = client.get(f"{MOUNT_PREFIX}/pricing")
    assert res.status_code == 200
    body = res.json()
    assert {"builtin", "custom", "scale", "price_unit", "notes"} <= set(body)
    assert body["scale"] == 100_000_000
    assert isinstance(body["builtin"], list) and body["builtin"]
    assert find_bare_money_keys(body) == []


def test_custom_price_roundtrip_and_clear(client):
    res = client.put(f"{MOUNT_PREFIX}/pricing/custom", json={"model": "my-custom-model", "pricing": VALID_QUOTE})
    assert res.status_code == 200
    assert res.json()["pricing"] == VALID_QUOTE
    assert any(c["model"] == "my-custom-model" for c in res.json()["custom"])

    # overview reflects it
    overview = client.get(f"{MOUNT_PREFIX}/pricing").json()
    assert any(c["model"] == "my-custom-model" for c in overview["custom"])

    # clear with null
    res = client.put(f"{MOUNT_PREFIX}/pricing/custom", json={"model": "my-custom-model", "pricing": None})
    assert res.status_code == 200
    assert not any(c["model"] == "my-custom-model" for c in res.json()["custom"])


def test_custom_price_validation_errors(client):
    for bad in (
        {"model": "m", "pricing": {"hit": "1", "miss": "2", "out": "8", "currency": "EUR"}},
        {"model": "m", "pricing": {"hit": "1", "out": "8", "currency": "CNY"}},
        {"model": "m", "pricing": {"hit": "-1", "miss": "2", "out": "8", "currency": "CNY"}},
        {"model": "", "pricing": VALID_QUOTE},
        {"pricing": VALID_QUOTE},
    ):
        res = client.put(f"{MOUNT_PREFIX}/pricing/custom", json=bad)
        assert res.status_code == 422, bad


def test_custom_price_requires_loopback(client_strict_loopback):
    res = client_strict_loopback.put(
        f"{MOUNT_PREFIX}/pricing/custom", json={"model": "m", "pricing": VALID_QUOTE}
    )
    assert res.status_code == 403


def test_custom_price_feeds_settlement(client, hermes_home):
    """End-to-end: custom price → ingest settlement uses it (frozen snapshot)."""
    from whale_core.db import connect as db_connect
    from whale_core.migrations import migrate

    client.put(f"{MOUNT_PREFIX}/pricing/custom", json={"model": "my-custom-model", "pricing": VALID_QUOTE})
    conn = db_connect(hermes_home / "whale-widget" / "whale.db")
    migrate(conn)
    try:
        result = ingest_turn(conn, _turn())  # 1M miss + 1M out → 2 + 8 = 10 CNY
        assert result["status"] == "accepted"
        row = conn.execute(
            "SELECT estimated_cost_units, currency, cost_basis, pricing_snapshot_json FROM turn_cost"
        ).fetchone()
        assert row["estimated_cost_units"] == 10 * 100_000_000
        assert row["currency"] == "CNY"
        assert row["cost_basis"] == "whale_pricing"
        snapshot = row["pricing_snapshot_json"]
        assert snapshot is not None and '"source": "custom"' in snapshot
    finally:
        conn.close()


def test_unknown_model_stays_null_not_zero(client, hermes_home):
    """Honesty: no price resolvable → NULL cost, never 0 (DATA_MODEL §8.3)."""
    from whale_core.db import connect as db_connect
    from whale_core.migrations import migrate

    conn = db_connect(hermes_home / "whale-widget" / "whale.db")
    migrate(conn)
    try:
        ingest_turn(conn, _turn(model="totally-unknown-model"))
        row = conn.execute(
            "SELECT estimated_cost_units, pricing_status FROM turn_cost"
        ).fetchone()
        assert row["estimated_cost_units"] is None
        assert row["pricing_status"] == "unknown_model"
    finally:
        conn.close()
