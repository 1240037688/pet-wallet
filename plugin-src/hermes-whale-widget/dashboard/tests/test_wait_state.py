"""REM domain (M8) — wait bridge: /ingest/wait-event, /wait-state, and the
agent-half approval observer hooks (approval-state.json).

Covers: slot open/close round-trip + notification lifecycle, strict whitelist
validation (400s, no answer content / secrets), loopback guard, /wait-state
shape, approval-state.json atomic writes + corruption fallback, hook
registration failure silence, and the plugin-root wiring.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from conftest import MOUNT_PREFIX

PLUGIN_SRC = Path(__file__).resolve().parents[2]  # plugin-src/hermes-whale-widget
APPROVAL_HOOK_PATH = PLUGIN_SRC / "whale_agent" / "approval_hook.py"
ROOT_INIT_PATH = PLUGIN_SRC / "__init__.py"

OPEN = {"kind": "question", "phase": "open", "tool_id": "tool-1", "session_id": "sess-a"}
CLOSE = {"kind": "question", "phase": "close", "tool_id": "tool-1", "session_id": "sess-a"}


@pytest.fixture(scope="module")
def approval_hook():
    """Load whale_agent/approval_hook.py by path (stdlib-only module)."""
    spec = importlib.util.spec_from_file_location("whale_approval_hook_test", APPROVAL_HOOK_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {APPROVAL_HOOK_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def runtime_conn():
    from whale_core import api as whale_api

    return whale_api._ensure_runtime().conn


def notif_rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM notification ORDER BY id").fetchall()]


# ---------------------------------------------------------------------------
# POST /ingest/wait-event — slot + notification lifecycle
# ---------------------------------------------------------------------------


def test_wait_event_open_records_slot_and_fires_notification(client):
    res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=OPEN)
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "accepted"
    assert body["phase"] == "open"
    assert body["slot"]["tool_id"] == "tool-1"

    conn = runtime_conn()
    row = conn.execute("SELECT value FROM whale_meta WHERE key = 'wait.question.tool-1'").fetchone()
    assert row is not None
    stored = json.loads(row["value"])
    assert stored["session_id"] == "sess-a"
    assert isinstance(stored["since"], int)

    # persistent wait notification fired once (dedup wait:question:<tool_id>)
    rows = [r for r in notif_rows(conn) if r["kind"] == "wait_input"]
    assert len(rows) == 1
    assert rows[0]["dedup_key"] == "wait:question:tool-1"
    assert rows[0]["rank"] == 4
    assert rows[0]["ttl_ms"] == 0  # 常驻等待泡

    # re-open (idempotent replay) → slot refreshed, no second notification
    client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=OPEN)
    assert len([r for r in notif_rows(runtime_conn()) if r["kind"] == "wait_input"]) == 1


def test_wait_event_close_clears_slot_and_dismisses_notification(client):
    client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=OPEN)
    res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=CLOSE)
    assert res.status_code == 200
    body = res.json()
    assert body["phase"] == "close"
    assert body["removed"] is True
    assert body["dismissed"] is True

    conn = runtime_conn()
    assert conn.execute("SELECT COUNT(*) FROM whale_meta WHERE key = 'wait.question.tool-1'").fetchone()[0] == 0
    assert [r for r in notif_rows(conn) if r["kind"] == "wait_input"][0]["dismissed_at"] is not None

    state = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert state["question_slots"] == []
    assert "wait:question:tool-1" not in state["fired_dedup_keys"]


@pytest.mark.parametrize(
    "payload, snippet",
    [
        ({"kind": "question", "phase": "open", "tool_id": "t"}, "session_id"),
        ({"kind": "question", "phase": "open", "session_id": "s"}, "tool_id"),
        ({"kind": "question", "tool_id": "t", "session_id": "s"}, "phase"),
        ({"phase": "open", "tool_id": "t", "session_id": "s"}, "kind"),
        ({"kind": "approval", "phase": "open", "tool_id": "t", "session_id": "s"}, "kind"),
        ({"kind": "question", "phase": "pause", "tool_id": "t", "session_id": "s"}, "phase"),
        ({"kind": "question", "phase": "open", "tool_id": 42, "session_id": "s"}, "tool_id"),
        ({"kind": "question", "phase": "open", "tool_id": "t", "session_id": ""}, "session_id"),
        ({"kind": "question", "phase": "open", "tool_id": "t" * 300, "session_id": "s"}, "tool_id"),
        # whitelist: unknown fields are rejected so answer content can never ride along
        (
            {"kind": "question", "phase": "open", "tool_id": "t", "session_id": "s", "answer": "2 + 2 = 4"},
            "unknown field",
        ),
        ([1, 2], "JSON object"),
        ("nope", "JSON object"),
    ],
)
def test_wait_event_malformed_400(client, payload, snippet):
    res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=payload)
    assert res.status_code == 400
    assert snippet in res.json()["detail"]


def test_wait_event_credential_shaped_tool_id_rejected(client):
    payload = {**OPEN, "tool_id": "sk-test-fake-abcdefgh1234"}
    res = client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=payload)
    assert res.status_code == 400
    assert "credential" in res.json()["detail"]


def test_wait_event_requires_loopback(client_strict_loopback):
    res = client_strict_loopback.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=OPEN)
    assert res.status_code == 403


# ---------------------------------------------------------------------------
# GET /wait-state — merged waiting surface
# ---------------------------------------------------------------------------


def test_wait_state_shape_contract(client):
    body = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert set(body) == {"question_slots", "approval_slots", "fired_dedup_keys"}
    assert body["question_slots"] == []
    assert body["approval_slots"] == []
    assert body["fired_dedup_keys"] == []


def test_wait_state_lists_question_slots_and_fired_keys(client):
    client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=OPEN)
    client.post(
        f"{MOUNT_PREFIX}/ingest/wait-event",
        json={**OPEN, "tool_id": "tool-2", "session_id": "sess-b"},  # multi-session slots
    )
    body = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    tools = {slot["tool_id"]: slot for slot in body["question_slots"]}
    assert set(tools) == {"tool-1", "tool-2"}
    assert tools["tool-1"]["session_id"] == "sess-a"
    assert isinstance(tools["tool-1"]["since"], int)
    assert "wait:question:tool-1" in body["fired_dedup_keys"]
    assert "wait:question:tool-2" in body["fired_dedup_keys"]


def test_wait_state_repeated_polls_do_not_duplicate_notifications(client):
    client.post(f"{MOUNT_PREFIX}/ingest/wait-event", json=OPEN)
    client.get(f"{MOUNT_PREFIX}/wait-state")
    client.get(f"{MOUNT_PREFIX}/wait-state")
    client.get(f"{MOUNT_PREFIX}/wait-state")
    assert len([r for r in notif_rows(runtime_conn()) if r["kind"] == "wait_input"]) == 1


# ---------------------------------------------------------------------------
# approval-state.json (written by the agent-half hooks, read by the bridge)
# ---------------------------------------------------------------------------


def test_wait_state_merges_approval_slots_and_syncs_notifications(client, approval_hook, hermes_home):
    approval_hook.add_entry(
        {"session_key": "webui:s1", "surface": "gateway", "tool_call_id": "tc-9", "turn_id": "t-9"},
        now=1_792_000_000_000,
    )
    body = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert len(body["approval_slots"]) == 1
    slot = body["approval_slots"][0]
    assert slot["id"] == "webui:s1#tc-9"
    assert slot["kind"] == "approval"
    assert slot["tool"] == "tc-9"
    assert slot["since"] == 1_792_000_000_000
    assert "wait:approval:webui:s1#tc-9" in body["fired_dedup_keys"]

    conn = runtime_conn()
    rows = [r for r in notif_rows(conn) if r["kind"] == "wait_approval"]
    assert len(rows) == 1
    assert rows[0]["dedup_key"] == "wait:approval:webui:s1#tc-9"

    # resolution → file entry removed → notification dismissed on the next read
    approval_hook.remove_entry(
        {"session_key": "webui:s1", "surface": "gateway", "tool_call_id": "tc-9", "turn_id": "t-9"},
    )
    body = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert body["approval_slots"] == []
    assert "wait:approval:webui:s1#tc-9" not in body["fired_dedup_keys"]
    assert notif_rows(conn)[0]["dismissed_at"] is not None


def test_wait_state_survives_corrupt_approval_file(client, approval_hook, hermes_home):
    path = approval_hook.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{definitely not json")
    body = client.get(f"{MOUNT_PREFIX}/wait-state").json()
    assert body["approval_slots"] == []  # fail-open for the display surface


# ---------------------------------------------------------------------------
# whale_agent/approval_hook.py — observer hooks
# ---------------------------------------------------------------------------


def test_hook_pre_records_then_post_clears(approval_hook, hermes_home):
    kwargs = {
        "command": "rm -rf TOPSECRET-TARGET", "description": "TOPSECRET-DESC",
        "pattern_key": "pk-rm", "pattern_keys": ["pk-rm"], "session_key": "webui:s1",
        "surface": "gateway", "tool_call_id": "tc-1", "turn_id": "t-1",
    }
    approval_hook._on_pre_approval_request(**kwargs)

    path = approval_hook.state_path()
    assert path.exists()
    entries = approval_hook.read_state()
    assert len(entries) == 1
    entry = entries[0]
    assert set(entry) == {"id", "kind", "tool", "since"}  # ids + timestamp ONLY
    assert entry["id"] == "webui:s1#tc-1"
    assert entry["kind"] == "approval"
    assert entry["tool"] == "tc-1"

    # privacy: no approval payload may reach the file
    raw = path.read_text(encoding="utf-8")
    assert "rm -rf" not in raw
    assert "TOPSECRET" not in raw
    assert "pk-rm" not in raw

    # atomic write leaves no tmp litter
    assert list(path.parent.glob("approval-state.json*.tmp")) == []

    approval_hook._on_post_approval_response(**kwargs, choice="once")
    assert approval_hook.read_state() == []
    assert list(path.parent.glob("approval-state.json*.tmp")) == []


def test_hook_non_gateway_surfaces_ignored(approval_hook, hermes_home):
    approval_hook._on_pre_approval_request(
        command="x", description="y", session_key="cli:s", surface="cli", tool_call_id="tc",
    )
    approval_hook._on_pre_approval_request(
        command="x", description="y", session_key="smart:s", surface="smart", tool_call_id="tc",
    )
    approval_hook._on_pre_approval_request(command="x", description="y", tool_call_id="tc")  # no surface
    assert approval_hook.read_state() == []


def test_hook_corrupt_state_file_fallback(approval_hook, hermes_home):
    path = approval_hook.state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"{{{corrupt")
    assert approval_hook.read_state() == []  # corrupt → empty, never raises
    approval_hook._on_pre_approval_request(
        command="x", description="y", session_key="webui:s", surface="gateway", tool_call_id="tc-2",
    )
    entries = approval_hook.read_state()
    assert [e["id"] for e in entries] == ["webui:s#tc-2"]  # rewritten atomically


def test_hook_session_prefix_fallback_pairing(approval_hook, hermes_home):
    """When correlation ids vanish between pre and post, the session-scoped
    slot is still cleared (approvals block the session)."""
    approval_hook._on_pre_approval_request(
        command="x", description="y", session_key="webui:s7", surface="gateway", tool_call_id="tc-9",
    )
    approval_hook._on_post_approval_response(
        command="x", description="y", session_key="webui:s7", surface="gateway", choice="timeout",
    )
    assert approval_hook.read_state() == []


def test_hook_multiple_sessions_do_not_interfere(approval_hook, hermes_home):
    approval_hook._on_pre_approval_request(
        command="x", description="y", session_key="webui:s1", surface="gateway", tool_call_id="a",
    )
    approval_hook._on_pre_approval_request(
        command="x", description="y", session_key="webui:s2", surface="gateway", tool_call_id="b",
    )
    assert {e["id"] for e in approval_hook.read_state()} == {"webui:s1#a", "webui:s2#b"}
    approval_hook._on_post_approval_response(
        command="x", description="y", session_key="webui:s1", surface="gateway", tool_call_id="a", choice="once",
    )
    assert [e["id"] for e in approval_hook.read_state()] == ["webui:s2#b"]


def test_hook_callback_never_raises(approval_hook, hermes_home, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(approval_hook, "add_entry", boom)
    approval_hook._on_pre_approval_request(  # must swallow, not propagate
        command="x", description="y", session_key="s", surface="gateway", tool_call_id="tc",
    )
    monkeypatch.setattr(approval_hook, "remove_entry", boom)
    approval_hook._on_post_approval_response(
        command="x", description="y", session_key="s", surface="gateway", tool_call_id="tc", choice="once",
    )


# ---------------------------------------------------------------------------
# registration wiring (plugin root __init__.py + register_approval_hooks)
# ---------------------------------------------------------------------------


class _RecordingCtx:
    def __init__(self, fail=False):
        self.registered = []
        self._fail = fail

    def register_hook(self, name, callback):
        if self._fail:
            raise RuntimeError("hook bus unavailable")
        self.registered.append(name)
        return object()


def test_register_approval_hooks_wires_both_observers(approval_hook):
    ctx = _RecordingCtx()
    handles = approval_hook.register_approval_hooks(ctx)
    assert len(handles) == 2
    assert set(ctx.registered) == {"pre_approval_request", "post_approval_response"}


def test_register_approval_hooks_missing_ctx_capability_is_silent(approval_hook):
    assert approval_hook.register_approval_hooks(None) == []
    assert approval_hook.register_approval_hooks(object()) == []  # no register_hook attr


def test_register_approval_hooks_failure_is_swallowed(approval_hook):
    assert approval_hook.register_approval_hooks(_RecordingCtx(fail=True)) == []


def test_plugin_root_register_wires_hooks_never_raises():
    """The loader imports plugin __init__.py as a package (M0 probe); emulate
    that context and confirm register(ctx) completes without raising."""
    spec = importlib.util.spec_from_file_location(
        "whale_plugin_root_test", ROOT_INIT_PATH, submodule_search_locations=[str(PLUGIN_SRC)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {ROOT_INIT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    ctx = _RecordingCtx()
    module.register(ctx)  # must not raise
    assert set(ctx.registered) == {"pre_approval_request", "post_approval_response"}
    module.register(None)  # broken ctx → logged, swallowed
    module.register(_RecordingCtx(fail=True))  # failing bus → logged, swallowed


def test_plugin_yaml_declares_the_observed_hooks():
    """plugin.yaml must declare exactly the hooks the agent half registers
    (admission rule: declared capabilities match actual registration)."""
    raw = (PLUGIN_SRC / "plugin.yaml").read_text(encoding="utf-8")
    assert "provides_hooks:" in raw
    assert "- pre_approval_request" in raw
    assert "- post_approval_response" in raw
