"""Config read/write: defaults, deep merge, atomic write, whitelist validation,
and the /config endpoints (GET / PUT) at L2."""

from __future__ import annotations

import json

from conftest import MOUNT_PREFIX
from whale_core import config


def test_missing_config_returns_defaults(hermes_home):
    loaded = config.load_config()
    assert loaded == config.DEFAULTS
    assert loaded["bubbles"]["turn_cost_ttl_ms"] == 5000


def test_data_dir_respects_explicit_home(tmp_path):
    d = config.data_dir(tmp_path)
    assert d == tmp_path / "pet-wallet"
    assert d.exists()


def test_data_dir_respects_hermes_home_env(hermes_home):
    assert config.data_dir() == hermes_home / "pet-wallet"


def test_save_and_load_roundtrip_with_deep_merge(hermes_home):
    merged = config.save_config({"thresholds": {"balance_low": 5.0}})
    assert merged["thresholds"]["balance_low"] == 5.0
    # untouched nested default survives
    assert merged["thresholds"]["daily_budget"] is None
    # file on disk holds the merged document
    on_disk = json.loads((hermes_home / "pet-wallet" / "config.json").read_text("utf-8"))
    assert on_disk["thresholds"]["balance_low"] == 5.0
    # reload agrees
    assert config.load_config()["thresholds"]["balance_low"] == 5.0


def test_deep_merge_does_not_mutate_defaults(hermes_home):
    config.save_config({"bubbles": {"enabled": False}})
    assert config.DEFAULTS["bubbles"]["enabled"] is True
    assert config.load_config()["bubbles"]["turn_cost_ttl_ms"] == 5000


def test_unknown_section_rejected_without_echoing_values():
    import pytest

    from whale_core.config import validate_config_update

    with pytest.raises(ValueError) as excinfo:
        validate_config_update({"no_such_section": "SUPER-SECRET-VALUE"})
    # error must name the section but never echo the value
    assert "no_such_section" in str(excinfo.value)
    assert "SUPER-SECRET-VALUE" not in str(excinfo.value)


def test_credential_like_fields_rejected_anywhere():
    import pytest

    from whale_core.config import validate_config_update

    for payload in (
        {"api_key": "whatever"},
        {"reminders": {"token": "whatever"}},
        {"bubbles": {"credentials": []}},
    ):
        with pytest.raises(ValueError):
            validate_config_update(payload)


def test_non_object_payload_rejected():
    import pytest

    from whale_core.config import validate_config_update

    for payload in ([1, 2], "x", None):
        with pytest.raises(ValueError):
            validate_config_update(payload)


def test_corrupt_config_quarantined_and_defaults_restored(hermes_home):
    path = config.config_path(hermes_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json at all", encoding="utf-8")
    loaded = config.load_config(hermes_home)
    assert loaded == config.DEFAULTS
    assert list(path.parent.glob("config.json.corrupt-*"))
    # next write starts clean
    config.save_config({"bubbles": {"enabled": False}}, home=hermes_home)
    assert config.load_config(hermes_home)["bubbles"]["enabled"] is False


def test_reset_defaults_restores_factory_state(hermes_home):
    config.save_config({"thresholds": {"balance_low": 1.0}}, home=hermes_home)
    config.reset_defaults(hermes_home)
    assert config.load_config(hermes_home) == config.DEFAULTS


# ── /config endpoints (L2) ──────────────────────────────────────────────────


def test_get_config_endpoint_returns_defaults(client):
    res = client.get(f"{MOUNT_PREFIX}/config")
    assert res.status_code == 200
    assert res.json() == config.DEFAULTS


def test_put_config_endpoint_merges_and_persists(client, hermes_home):
    res = client.put(f"{MOUNT_PREFIX}/config", json={"bubbles": {"turn_cost_ttl_ms": 8000}})
    assert res.status_code == 200
    body = res.json()
    assert body["bubbles"]["turn_cost_ttl_ms"] == 8000
    assert body["bubbles"]["enabled"] is True
    # persisted: a fresh GET reflects the write
    assert client.get(f"{MOUNT_PREFIX}/config").json()["bubbles"]["turn_cost_ttl_ms"] == 8000
    on_disk = json.loads((hermes_home / "pet-wallet" / "config.json").read_text("utf-8"))
    assert on_disk["bubbles"]["turn_cost_ttl_ms"] == 8000


def test_put_config_endpoint_rejects_unknown_section(client):
    res = client.put(f"{MOUNT_PREFIX}/config", json={"hax": {}})
    assert res.status_code == 422


def test_put_config_endpoint_never_accepts_credential_fields(client):
    res = client.put(f"{MOUNT_PREFIX}/config", json={"api_key": "sk-test-fake-config-reject"})
    assert res.status_code == 422
    # and nothing was persisted
    assert "api_key" not in client.get(f"{MOUNT_PREFIX}/config").json()
