"""M4 track② — PRV domain (all provider I/O via httpx.MockTransport, never real
APIs) + differencing + five-state machine + adjustment 409 + security asserts.

Fake keys use the sanctioned ``sk-test-fake-`` prefix (TEST_PLAN §2.1).
"""

from __future__ import annotations

import json

import httpx
import pytest

from conftest import MOUNT_PREFIX
from whale_core import balance_ledger, clock
from whale_core.db import connect as db_connect
from whale_core.migrations import migrate
from whale_core.providers import base as provider_base
from whale_core.providers import gateway
from whale_core.providers.deepseek import DeepSeekProvider, select_currency
from whale_core.security import find_bare_money_keys

BASE_MS = 1_792_000_000_000
FAKE_KEY = "sk-test-fake-deepseek-000000000001"

BALANCE_BODY = {
    "is_available": True,
    "balance_infos": [
        {"currency": "CNY", "total_balance": "110.00", "granted_balance": "10.00", "topped_up_balance": "100.00"},
        {"currency": "USD", "total_balance": "5.00"},
    ],
}


@pytest.fixture(autouse=True)
def _pin_clock():
    clock.set_clock(lambda: BASE_MS / 1000.0)
    yield
    clock.reset_clock()


@pytest.fixture()
def conn(tmp_path):
    c = db_connect(tmp_path / "whale.db")
    migrate(c)
    yield c
    c.close()


@pytest.fixture()
def fake_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", FAKE_KEY)
    return FAKE_KEY


def _transport(handler):
    return httpx.MockTransport(handler)


def _refresh(conn, body=BALANCE_BODY, *, status=200, key=fake_key):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.deepseek.com/user/balance"
        assert request.headers.get("Authorization") == f"Bearer {FAKE_KEY}"
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return balance_ledger.refresh_balance(conn, transport=_transport(handler))


# ---------------------------------------------------------------------------
# provider selection (pure)
# ---------------------------------------------------------------------------

def test_select_currency_prefers_nonzero_cny():
    infos = [
        {"currency": "USD", "total_balance": "5.00"},
        {"currency": "CNY", "total_balance": "0.00"},
        {"currency": "CNY", "total_balance": "42.00"},
    ]
    assert select_currency(infos)["total_balance"] == "42.00"


def test_select_currency_any_nonzero_then_cny_then_first():
    assert select_currency([{"currency": "USD", "total_balance": "0"}, {"currency": "EUR", "total_balance": "3"}])["currency"] == "EUR"
    assert select_currency([{"currency": "USD", "total_balance": "0"}, {"currency": "CNY", "total_balance": "0"}])["currency"] == "CNY"
    assert select_currency([{"currency": "USD", "total_balance": "0"}, {"currency": "EUR", "total_balance": "0"}])["currency"] == "USD"
    assert select_currency([]) is None


# ---------------------------------------------------------------------------
# PRV domain — one happy path + every failure mode
# ---------------------------------------------------------------------------

def test_ok_fetch_books_snapshot_and_state(conn, fake_key):
    state = _refresh(conn)
    assert state["state"] == "ok"
    assert state["observed_balance_units"] == 110 * 100_000_000
    assert state["granted_units"] == 10 * 100_000_000
    assert state["topped_up_units"] == 100 * 100_000_000
    assert state["currency"] == "CNY"
    assert state["fingerprint"] == gateway.fingerprint(FAKE_KEY)
    assert state["stale"] is False
    row = conn.execute("SELECT raw_response_json, fetch_state FROM balance_snapshot").fetchone()
    assert row["fetch_state"] == "ok"
    raw = json.loads(row["raw_response_json"])
    assert raw["is_available"] is True
    assert FAKE_KEY not in json.dumps(state)  # credential never leaves the half


def test_not_configured_parks_without_network(conn):
    def handler(request):  # any call = failure
        raise AssertionError("network must not be touched without credentials")

    state = balance_ledger.refresh_balance(conn, transport=_transport(handler))
    assert state["state"] == "unknown"
    assert state["refresh_skipped"] == "not_configured"
    assert state["credential"]["configured"] is False


@pytest.mark.parametrize(
    "status,body,kind",
    [
        (401, {"error": "auth"}, "auth"),
        (403, {"error": "auth"}, "auth"),
        (429, {"error": "rate"}, "rate_limited"),
        (500, {"error": "boom"}, "server"),
        (200, "not-json{", "bad_response"),
        (200, {"is_available": True}, "bad_response"),  # missing path
        (200, {"balance_infos": []}, "bad_response"),
        (200, {"balance_infos": [{"currency": "CNY", "total_balance": "abc"}]}, "bad_response"),
    ],
)
def test_error_modes_keep_state_clean(conn, fake_key, status, body, kind):
    state = _refresh(conn, body=body, status=status)
    assert state["state"] == "error"
    assert state["error"]["kind"] == kind
    assert state["error"]["at"] == BASE_MS
    assert state["observed_balance_units"] is None  # nothing ever observed
    assert conn.execute("SELECT COUNT(*) c FROM balance_snapshot").fetchone()["c"] == 0


def test_zero_balance_is_distinct_from_error(conn, fake_key):
    zero_body = {"is_available": True, "balance_infos": [{"currency": "CNY", "total_balance": "0.00"}]}
    state = _refresh(conn, body=zero_body)
    assert state["state"] == "zero"
    assert state["observed_balance_units"] == 0


def test_timeout_maps_to_timeout_kind(conn, fake_key):
    def handler(request):
        raise httpx.ConnectTimeout("timeout")

    state = balance_ledger.refresh_balance(conn, transport=_transport(handler))
    assert state["state"] == "error"
    assert state["error"]["kind"] == "timeout"


# ---------------------------------------------------------------------------
# differencing + state machine transitions
# ---------------------------------------------------------------------------

def test_down_is_spend_up_is_credit_never_cancels(conn, fake_key):
    _refresh(conn)  # 110
    clock.set_clock(lambda: (BASE_MS + 1000) / 1000.0)
    state = _refresh(conn, body={**BALANCE_BODY, "balance_infos": [dict(BALANCE_BODY["balance_infos"][0], total_balance="90.00")]})
    assert state["state"] == "ok"
    clock.set_clock(lambda: (BASE_MS + 2000) / 1000.0)
    _refresh(conn)  # back to 110 → top-up path
    summary = balance_ledger.balance_summary(conn, now=BASE_MS + 2000)
    day = summary["days"][0]
    assert day["observed_spend_units"] == 20 * 100_000_000  # 110→90 only
    assert day["credit_units"] == 20 * 100_000_000  # 90→110 booked as credit
    assert day["needs_review"] is False


def test_large_gap_marks_day_partial(conn, fake_key):
    _refresh(conn)
    clock.set_clock(lambda: (BASE_MS + 601 * 1000) / 1000.0)  # >10 min gap
    _refresh(conn)
    summary = balance_ledger.balance_summary(conn, now=BASE_MS + 601 * 1000)
    assert summary["days"][0]["partial"] is True
    assert summary["days"][0]["gap_seconds"] >= 600


def test_error_then_recover_clears_error(conn, fake_key):
    _refresh(conn)
    clock.set_clock(lambda: (BASE_MS + 1000) / 1000.0)
    _refresh(conn, status=500)  # error, last known kept
    state = balance_ledger.balance_state(conn, now=BASE_MS + 1000)
    assert state["state"] == "error"
    assert state["observed_balance_units"] == 110 * 100_000_000
    clock.set_clock(lambda: (BASE_MS + 2000) / 1000.0)
    state = _refresh(conn)
    assert state["state"] == "ok"
    assert state["error"] is None


def test_stale_after_ttl(conn, fake_key):
    _refresh(conn)
    state = balance_ledger.balance_state(conn, now=BASE_MS + balance_ledger.FRESH_TTL_MS + 1)
    assert state["state"] == "stale"
    assert state["observed_balance_units"] == 110 * 100_000_000  # last known survives


# ---------------------------------------------------------------------------
# adjustment (explicit reconciliation; revision 409)
# ---------------------------------------------------------------------------

def _seed_two_observations(conn, fake_key):
    _refresh(conn)  # 110
    clock.set_clock(lambda: (BASE_MS + 1000) / 1000.0)
    _refresh(conn, body={**BALANCE_BODY, "balance_infos": [dict(BALANCE_BODY["balance_infos"][0], total_balance="90.00")]})


def test_adjustment_implied_usage_formula(conn, fake_key):
    _seed_two_observations(conn, fake_key)
    day = balance_ledger.balance_summary(conn, now=BASE_MS + 1000)["days"][0]["day"]
    result = balance_ledger.apply_adjustment(
        conn, scope=gateway.fingerprint(FAKE_KEY), day=day, currency="CNY",
        credits_units=5 * 100_000_000, other_debits_units=2 * 100_000_000, revision=None,
    )
    # implied = opening(110) + credits(5) − other debits(2) − last(90) = 23
    assert result["adjustment_implied_usage_units"] == 23 * 100_000_000
    row = conn.execute("SELECT revision FROM daily_summary WHERE track='balance'").fetchone()
    assert row["revision"] == result["revision"]


def test_adjustment_revision_conflict(conn, fake_key):
    _seed_two_observations(conn, fake_key)
    day = balance_ledger.balance_summary(conn, now=BASE_MS + 1000)["days"][0]["day"]
    first = balance_ledger.apply_adjustment(
        conn, scope=gateway.fingerprint(FAKE_KEY), day=day, currency="CNY",
        credits_units=0, other_debits_units=0, revision=None,
    )
    with pytest.raises(balance_ledger.AdjustmentConflict):
        balance_ledger.apply_adjustment(
            conn, scope=gateway.fingerprint(FAKE_KEY), day=day, currency="CNY",
            credits_units=0, other_debits_units=0, revision="stale-revision",
        )
    # correct revision succeeds
    balance_ledger.apply_adjustment(
        conn, scope=gateway.fingerprint(FAKE_KEY), day=day, currency="CNY",
        credits_units=0, other_debits_units=0, revision=first["revision"],
    )


# ---------------------------------------------------------------------------
# REST surface + security
# ---------------------------------------------------------------------------

def test_balance_rest_naming_lint_and_validation(client, fake_key):
    body = client.get(f"{MOUNT_PREFIX}/balance").json()
    assert body["state"] in {"unknown", "zero", "error", "stale", "ok"}
    assert find_bare_money_keys(body) == []
    assert client.get(f"{MOUNT_PREFIX}/balance/summary").status_code == 200
    res = client.post(f"{MOUNT_PREFIX}/balance/adjustment", json={"day": "2026-10-03"})
    assert res.status_code == 404  # no observations → nothing to correct
    res = client.post(f"{MOUNT_PREFIX}/balance/adjustment", json={"day": "bogus"})
    assert res.status_code == 422


def test_adjustment_conflict_via_rest_returns_409(client, fake_key):
    # seed via the ledger directly (REST refresh would need a transport; the
    # mock lives at the ledger layer, TEST_PLAN §2.1)
    from whale_core import api as whale_api

    whale_api.reset_runtime()
    conn = whale_api._ensure_runtime().conn
    _seed_two_observations(conn, fake_key)
    day = balance_ledger.balance_summary(conn, now=BASE_MS + 1000)["days"][0]["day"]
    res = client.post(f"{MOUNT_PREFIX}/balance/adjustment", json={"day": day, "revision": "wrong"})
    assert res.status_code == 409


def test_credentials_file_fallback_source(conn, hermes_home):
    cred_dir = hermes_home / "whale-widget"
    cred_dir.mkdir(parents=True, exist_ok=True)
    (cred_dir / "credentials.json").write_text(
        json.dumps({"providers": {"deepseek": FAKE_KEY}}), encoding="utf-8"
    )
    cred = gateway.resolve_credential("deepseek")
    assert cred is not None and cred["source"] == "credentials_file"
    status = gateway.credential_status("deepseek")
    assert status["configured"] is True
    assert "key" not in status and FAKE_KEY not in json.dumps(status)


def test_outbound_origin_whitelist():
    with pytest.raises(ValueError):
        gateway.assert_allowed_origin("https://evil.example.com/user/balance", ["https://api.deepseek.com"])
    gateway.assert_allowed_origin("https://api.deepseek.com/user/balance", ["https://api.deepseek.com"])
