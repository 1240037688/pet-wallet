"""CON-01 — POST /ingest/turn contract: schema, idempotent response, malformed
payloads 4xx without echoing values, loopback guard, fail-closed 503."""

from __future__ import annotations

import time

import pytest

from conftest import MOUNT_PREFIX
from whale_core import api as whale_api
from whale_core.ingest import (
    compute_dedup_key,
    local_day_key,
    minute_bucket,
)

TURN = {
    "session_id": "sess-1",
    "profile": "default",
    "model": "deepseek-chat",
    "usage": {
        "input": 100, "output": 50, "reasoning": 10, "cache_read": 5, "cache_write": 2,
        "calls": 3, "cost_usd": 0.0123, "context_used": 1200, "context_max": 8192, "context_percent": 14.6,
    },
    "received_at": int(time.time() * 1000),
    "status": "complete",
    "after_reconnect": False,
}


def _rows(conn, table):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]


def test_valid_single_turn_accepted(client):
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=TURN)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["accepted"] == 1
    assert body["duplicate"] == 0


def test_batch_shape_counts(client):
    second = {**TURN, "session_id": "sess-2"}
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json={"turns": [TURN, second]})
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["accepted"] == 2
    assert body["duplicate"] == 0
    # M8 cross-package contract: accepted responses carry the settled array
    assert len(body["settled"]) == 2


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda p: p, id="bare object accepted"),
        pytest.param(lambda p: {"turns": [p]}, id="turns wrapper accepted"),
    ],
)
def test_both_request_shapes_accepted(client, mutate):
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=mutate(TURN))
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"


@pytest.mark.parametrize(
    "payload, snippet",
    [
        ([1, 2, 3], "JSON object"),
        ("nope", "JSON object"),
        ({**TURN, "session_id": ""}, "session_id"),
        ({k: v for k, v in TURN.items() if k != "session_id"}, "session_id"),
        ({**TURN, "session_id": 42}, "session_id"),
        ({k: v for k, v in TURN.items() if k != "received_at"}, "received_at"),
        ({**TURN, "received_at": "now"}, "received_at"),
        ({**TURN, "received_at": -5}, "received_at"),
        ({**TURN, "usage": None}, "usage"),
        ({**TURN, "usage": [1]}, "usage"),
        ({**TURN, "status": "weird"}, "status"),
        ({**TURN, "after_reconnect": "yes"}, "after_reconnect"),
        ({"turns": []}, "turns"),
        ({"turns": "nope"}, "turns"),
        ({"turns": [TURN] * 101}, "turns"),
    ],
)
def test_malformed_payloads_400(client, payload, snippet):
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload)
    assert res.status_code == 400
    assert snippet in res.json()["detail"]


def test_error_never_echoes_payload_values(client):
    secret_value = "TOPSECRET-VALUE-9x8y7z"
    payload = {**TURN, "session_id": secret_value * 40, "usage": secret_value}
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload)
    assert res.status_code == 400
    assert secret_value not in res.text


def test_credential_shaped_payload_rejected(client):
    """SEC-01/SEC-02 slice: credential shapes never reach the ledger."""
    payload = {**TURN, "usage": {"input": 1, "note": "sk-test-fake-abcdefgh1234"}}
    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=payload)
    assert res.status_code == 400
    assert "credential" in res.json()["detail"]


def test_ingest_rejects_non_loopback(client_strict_loopback):
    res = client_strict_loopback.post(f"{MOUNT_PREFIX}/ingest/turn", json=TURN)
    assert res.status_code == 403


def test_ingest_fail_closed_when_ledger_corrupt(client, hermes_home):
    """DATA_MODEL §7.4: corrupt ledger → 503, never a half write."""
    db_path = hermes_home / "whale-widget" / "whale.db"
    client.post(f"{MOUNT_PREFIX}/ingest/turn", json=TURN)  # initialise runtime
    whale_api.reset_runtime()
    db_path.write_bytes(b"this is definitely not a sqlite database" * 32)

    res = client.post(f"{MOUNT_PREFIX}/ingest/turn", json=TURN)
    assert res.status_code == 503
    assert "ledger unavailable" in res.json()["detail"]


# ---------------------------------------------------------------------------
# pure helpers pinned by vectors (M2 risk note: fix the formula with vectors)
# ---------------------------------------------------------------------------


def test_dedup_key_formula_pinned_by_vector():
    """DATA_MODEL §3.2 formula — changing the join order/format breaks this."""
    key = compute_dedup_key(
        "s1", "2026-10-03", 810, 1, "message.complete", "deepseek-chat",
        {"input": 100, "output": 50, "cache_read": 5, "cache_write": 2, "reasoning": 10},
        "token_only", 0,
    )
    assert key == "88b38a91759804128eca729a9dbdb30d35f61dcd"


def test_dedup_key_distinguishes_content():
    base = dict(
        session_id="s1", day="2026-10-03", minute=810, turn_seq=1,
        source_event="message.complete", model="m",
        toks={"input": 1, "output": 2, "cache_read": 0, "cache_write": 0, "reasoning": 0},
        cost_basis="token_only", estimated_cost_units=0,
    )
    keys = {compute_dedup_key(**base)}
    for field, value in (
        ("session_id", "s2"), ("day", "2026-10-04"), ("minute", 811), ("turn_seq", 2),
        ("model", "m2"),
    ):
        keys.add(compute_dedup_key(**{**base, field: value}))
    keys.add(compute_dedup_key(**{**base, "toks": {**base["toks"], "input": 9}}))
    assert len(keys) == 7  # every dimension changes the key


def test_local_day_and_minute_helpers():
    ms = 1_791_964_800_000  # arbitrary fixed epoch ms
    day = local_day_key(ms)
    assert day == time.strftime("%Y-%m-%d", time.localtime(ms / 1000.0))
    assert minute_bucket(ms) == ms // 60_000
    assert minute_bucket(59_999) == 0
    assert minute_bucket(60_000) == 1
