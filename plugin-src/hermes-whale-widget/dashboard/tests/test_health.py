"""CON-00 (health) + /meta contract tests + REST naming lint (DATA_MODEL §8.1)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from conftest import MOUNT_PREFIX, make_request
from whale_core.migrations import SCHEMA_VERSION
from whale_core.security import find_bare_money_keys, verify_loopback


def test_health_returns_schema_version(client):
    res = client.get(f"{MOUNT_PREFIX}/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert body["plugin"] == "whale-widget"
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["track3_state"] == "not_implemented"  # M2 replaces this
    assert body["contract_probe"] is None
    assert "version" in body


def test_health_repeated_calls_idempotent(client):
    first = client.get(f"{MOUNT_PREFIX}/health").json()
    second = client.get(f"{MOUNT_PREFIX}/health").json()
    assert first == second  # lazy runtime must not re-run migrations or duplicate state


def test_meta_reports_plugin_metadata(client):
    res = client.get(f"{MOUNT_PREFIX}/meta")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "whale-widget"
    assert body["label"] == "Whale Widget"
    assert body["api"] == "plugin_api.py"
    assert body["mounted_at"] == MOUNT_PREFIX
    assert body["schema_version"] == SCHEMA_VERSION


def test_no_bare_money_keys_in_any_get_response(client):
    """CON-03 precursor: /health /meta /config must never carry bare cost/spend/used."""
    for path in ("/health", "/meta", "/config"):
        body = client.get(f"{MOUNT_PREFIX}{path}").json()
        assert find_bare_money_keys(body) == [], f"bare money key in {path}"


def test_verify_loopback_rejects_remote():
    with pytest.raises(HTTPException) as excinfo:
        verify_loopback(make_request(host="10.0.0.5"))
    assert excinfo.value.status_code == 403
    with pytest.raises(HTTPException) as excinfo_v6:
        verify_loopback(make_request(host="192.168.1.4"))
    assert excinfo_v6.value.status_code == 403
    # loopback passes (no exception)
    verify_loopback(make_request(host="127.0.0.1"))
    verify_loopback(make_request(host="::1"))


def test_write_endpoints_reject_non_loopback(client_strict_loopback):
    """SEC-05 (M0 slice): TestClient's default host ('testclient') is not loopback."""
    res = client_strict_loopback.put(f"{MOUNT_PREFIX}/config", json={"bubbles": {"enabled": False}})
    assert res.status_code == 403


def test_health_survives_corrupt_db(client, hermes_home):
    """Fail-closed (DATA_MODEL §7.4): corrupt whale.db → ok:false + ledger_error, still 200."""
    db_path = hermes_home / "whale-widget" / "whale.db"
    client.get(f"{MOUNT_PREFIX}/health")  # create the db first
    assert db_path.exists()

    from whale_core import api as whale_api

    # reset FIRST: closing the last sqlite connection checkpoints the WAL and
    # would otherwise rewrite a valid db over the corruption
    whale_api.reset_runtime()
    db_path.write_bytes(b"this is definitely not a sqlite database" * 32)

    res = client.get(f"{MOUNT_PREFIX}/health")
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is False
    assert "ledger_error" in body
    # the corrupt file must have been quarantined, not overwritten
    leftovers = list(db_path.parent.glob("whale.db.corrupt-*"))
    assert leftovers, "corrupt db was not quarantined"
    assert find_bare_money_keys(body) == []
