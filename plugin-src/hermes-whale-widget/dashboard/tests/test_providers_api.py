"""WP-dashboard provider REST surface — /providers/status + /balance/all.

Contract pins (WP-dashboard task书):
  * rows iterate registry.known_ids() merged with credential_status + the
    five-state balance view;
  * unconfigured → configured=false, source='none', state='unknown' and NO
    credential fields (credential_id/fingerprint absent);
  * configured → credential_id + fingerprint present; observed_balance_units /
    currency only when actually observed (never fabricated, never 0-by-missing);
  * /balance/all = same rows, configured only (bubble data source);
  * responses carry no secret material ever (the fake key must not leak).
"""

from __future__ import annotations

import httpx
import pytest

from conftest import MOUNT_PREFIX
from whale_core import balance_ledger, clock
from whale_core.providers import gateway

BASE_MS = 1_792_000_000_000
FAKE_KEY = "sk-test-fake-deepseek-000000000001"
FAKE_FP = gateway.fingerprint(FAKE_KEY)


@pytest.fixture(autouse=True)
def _pin_clock():
    clock.set_clock(lambda: BASE_MS / 1000.0)
    yield
    clock.reset_clock()


@pytest.fixture()
def fake_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    return FAKE_KEY


def _seed_ok_observation(client):
    """Insert one genuine ok observation through the ledger (no network)."""
    from whale_core import api as whale_api

    whale_api.reset_runtime()
    whale_api._ensure_runtime()  # open the conn under the injected HERMES_HOME
    conn = whale_api._rt.conn
    balance_ledger.record_snapshot(
        conn,
        provider_id="deepseek",
        scope=FAKE_FP,
        currency="CNY",
        observed_balance_units=110_000_000,  # 1.10 CNY (1e8 fixed point)
        granted_units=None,
        topped_up_units=None,
        raw={"is_available": True},
        fetched_at=BASE_MS,
    )


def test_status_lists_known_providers_without_credentials(client):
    resp = client.get(f"{MOUNT_PREFIX}/providers/status")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"providers"}
    ids = [row["provider_id"] for row in body["providers"]]
    assert "deepseek" in ids
    for row in body["providers"]:
        assert set(row.keys()) == {"provider_id", "known", "configured", "source", "state"}
        assert row["known"] is True
        assert row["configured"] is False
        assert row["source"] == "none"
        assert row["state"] == "unknown"


def test_balance_all_is_empty_when_nothing_configured(client):
    resp = client.get(f"{MOUNT_PREFIX}/balance/all")
    assert resp.status_code == 200
    assert resp.json() == {"providers": []}


def test_status_configured_row_carries_credential_and_unknown_state(client, fake_key):
    resp = client.get(f"{MOUNT_PREFIX}/providers/status")
    assert resp.status_code == 200
    row = next(r for r in resp.json()["providers"] if r["provider_id"] == "deepseek")
    assert row["configured"] is True
    assert row["source"] in ("hermes_secret", "credentials_file")
    assert row["credential_id"].startswith("deepseek:")
    assert row["fingerprint"] == FAKE_FP
    assert row["state"] == "unknown"  # no observation yet — never guessed


def test_balance_all_returns_only_configured_with_observation(client, fake_key):
    _seed_ok_observation(client)
    resp = client.get(f"{MOUNT_PREFIX}/balance/all")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert [r["provider_id"] for r in providers] == ["deepseek"]
    row = providers[0]
    assert row["state"] == "ok"
    assert row["observed_balance_units"] == 110_000_000
    assert row["currency"] == "CNY"
    assert row["fingerprint"] == FAKE_FP
    assert row["credential_id"].startswith("deepseek:")


def test_error_state_keeps_last_known_balance(client, fake_key):
    """API failure ≠ 0: an error state still carries the last known amount."""
    from whale_core import api as whale_api

    _seed_ok_observation(client)
    conn = whale_api._rt.conn
    # simulate a stored provider error AFTER the good observation
    class _FakeErr(Exception):
        kind = "provider_http_error"
        http_status = 500

    balance_ledger._store_error(conn, "deepseek", _FakeErr(), BASE_MS + 1000)
    resp = client.get(f"{MOUNT_PREFIX}/providers/status")
    row = next(r for r in resp.json()["providers"] if r["provider_id"] == "deepseek")
    # FRESH_TTL not elapsed (clock pinned) but the error is newer than the snapshot
    assert row["state"] == "error"
    assert row["observed_balance_units"] == 110_000_000
    assert row["currency"] == "CNY"


def test_responses_never_leak_the_credential(client, fake_key):
    _seed_ok_observation(client)
    for path in ("/providers/status", "/balance/all"):
        text = client.get(f"{MOUNT_PREFIX}{path}").text
        assert FAKE_KEY not in text
        assert "api_key" not in text
        assert "Bearer" not in text


def test_balance_all_never_includes_unconfigured(client, monkeypatch):
    """Rows without credentials are excluded from the bubble data source."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    resp = client.get(f"{MOUNT_PREFIX}/balance/all")
    assert resp.status_code == 200
    assert resp.json() == {"providers": []}


def test_codex_quota_provider_mock(client, monkeypatch):
    """Test Codex quota reporting when configured."""
    from whale_core.providers.codex import CodexProvider

    mock_res = {
        "provider_id": "openai-codex",
        "name": "ChatGPT / Codex",
        "kind": "quota",
        "configured": True,
        "state": "ok",
        "plan": "Plus",
        "windows": [
            {"label": "Session", "used_percent": 25.0, "remaining_percent": 75.0, "reset_at": None, "detail": None},
            {"label": "Weekly", "used_percent": 30.0, "remaining_percent": 70.0, "reset_at": None, "detail": None},
        ],
        "details": ["You have 3 resets banked"],
        "fetched_at": BASE_MS,
    }
    monkeypatch.setattr(CodexProvider, "fetch_quota", lambda self, **kw: mock_res)

    resp = client.get(f"{MOUNT_PREFIX}/providers/status")
    assert resp.status_code == 200
    row = next(r for r in resp.json()["providers"] if r["provider_id"] == "openai-codex")
    assert row["configured"] is True
    assert row["kind"] == "quota"
    assert row["plan"] == "Plus"
    assert len(row["windows"]) == 2
    assert row["windows"][0]["label"] == "Session"
    assert row["windows"][0]["used_percent"] == 25.0
