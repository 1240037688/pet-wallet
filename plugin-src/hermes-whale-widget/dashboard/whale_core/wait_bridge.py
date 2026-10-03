"""Wait bridge — unified waiting surface for GET /wait-state (M8).

Merges the two wait-class signal sources into one polling endpoint:

* **question slots** — recorded by POST /ingest/wait-event (the desktop half
  forwards clarify ``tool.start``/``tool.complete``): one ``whale_meta`` key
  ``wait.question.<tool_id>`` per pending question, JSON
  ``{"session_id": ..., "since": <epoch-ms>}``. Payloads never carry any
  answer content — only ids and a timestamp.
* **approval slots** — read from ``<data_dir>/approval-state.json``, written by
  the agent half's observer hooks (``whale_agent/approval_hook.py``): entries
  ``{"id", "kind", "tool", "since"}`` only — never a command/description or
  any approval payload (WP-2 privacy rule).

Each read also syncs the persistent wait notifications (DATA_MODEL §2.10 dedup
``wait:question:<tool_id>`` / ``wait:approval:<id>``): a new pending slot fires
its notification once (INSERT OR IGNORE → replays are duplicates), a vanished
slot's notification is dismissed (等待解除收泡). ``fired_dedup_keys`` then lists
exactly the active reminders so the desktop can align after a reload without
re-ringing (DR-14).

The state file is read defensively: missing or corrupt → empty approval list
(fail-open for a display surface; the hook rewrites it atomically on the next
approval). The db is optional — a fail-closed ledger still reports approval
slots.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import config, notifications
from .clock import now_ms
from .logging_setup import get_logger

log = get_logger("wait_bridge")

QUESTION_KEY_PREFIX = "wait.question."
APPROVAL_STATE_FILENAME = "approval-state.json"

APPROVAL_ENTRY_KEYS = ("id", "kind", "tool", "since")


def _question_key(tool_id: str) -> str:
    return f"{QUESTION_KEY_PREFIX}{tool_id}"


# ---------------------------------------------------------------------------
# question slots (whale_meta)
# ---------------------------------------------------------------------------

def record_question_slot(conn: sqlite3.Connection, *, tool_id: str, session_id: str, now: int | None = None) -> dict[str, Any]:
    """Upsert one pending question slot; returns the slot dict.

    Re-opening an already-pending ``tool_id`` refreshes ``since`` (idempotent;
    the paired wait notification stays deduped — one ring per slot, DR-14).
    """
    ts = now_ms() if now is None else int(now)
    payload = json.dumps({"session_id": session_id, "since": ts}, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO whale_meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_question_key(tool_id), payload),
    )
    conn.commit()
    return {"tool_id": tool_id, "session_id": session_id, "since": ts}


def clear_question_slot(conn: sqlite3.Connection, *, tool_id: str) -> bool:
    """Remove a question slot (question answered / tool completed)."""
    cur = conn.execute("DELETE FROM whale_meta WHERE key = ?", (_question_key(tool_id),))
    conn.commit()
    return bool(cur.rowcount)


def question_slots(conn: sqlite3.Connection | None) -> list[dict[str, Any]]:
    """All pending question slots (unsorted order of whale_meta)."""
    if conn is None:
        return []
    slots: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT key, value FROM whale_meta WHERE key LIKE ? ORDER BY key",
        (QUESTION_KEY_PREFIX + "%",),
    ).fetchall()
    for row in rows:
        tool_id = str(row["key"])[len(QUESTION_KEY_PREFIX):]
        try:
            data = json.loads(row["value"])
        except (ValueError, TypeError):
            continue  # unreadable entry is skipped, never fatal
        if not isinstance(data, dict):
            continue
        since = data.get("since")
        slots.append({
            "tool_id": tool_id,
            "session_id": data.get("session_id"),
            "since": int(since) if isinstance(since, (int, float)) and not isinstance(since, bool) else None,
        })
    return slots


# ---------------------------------------------------------------------------
# approval slots (approval-state.json, written by the agent half)
# ---------------------------------------------------------------------------

def approval_state_path(home: str | Path | None = None) -> Path:
    return config.data_dir(home) / APPROVAL_STATE_FILENAME


def read_approval_state(home: str | Path | None = None) -> list[dict[str, Any]]:
    """Read pending approvals; missing/corrupt file → ``[]`` (fail-open).

    Only ``{id, kind, tool, since}`` entries are surfaced — the file is
    written exclusively by the observer hooks and never contains approval
    content (defensive filter: unexpected fields are dropped here too).
    """
    path = approval_state_path(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        log.warning("approval-state.json unreadable — treating as empty")
        return []
    if not isinstance(raw, dict):
        return []
    approvals = raw.get("approvals")
    if not isinstance(approvals, list):
        return []
    slots: list[dict[str, Any]] = []
    for entry in approvals:
        if not isinstance(entry, dict):
            continue
        since = entry.get("since")
        slots.append({
            "id": entry.get("id"),
            "kind": entry.get("kind"),
            "tool": entry.get("tool"),
            "since": int(since) if isinstance(since, (int, float)) and not isinstance(since, bool) else None,
        })
    return slots


def approval_slots(home: str | Path | None = None) -> list[dict[str, Any]]:
    """Pending approvals for /wait-state (alias of :func:`read_approval_state`)."""
    return read_approval_state(home)


# ---------------------------------------------------------------------------
# wait notifications sync + merged output
# ---------------------------------------------------------------------------

def _sync_wait_notifications(conn: sqlite3.Connection, approvals: list[dict[str, Any]], *, now: int) -> None:
    """Fire one wait notification per new pending slot; dismiss resolved ones.

    best-effort by design: any failure is logged and the merged /wait-state
    output is still produced from the slot sources themselves.
    """
    try:
        question_ids = {slot["tool_id"] for slot in question_slots(conn)}
        for tool_id in sorted(question_ids):
            if not tool_id:
                continue
            notifications.fire(
                conn,
                kind="wait_input",
                rank=notifications.RANK_WAIT,
                dedup_key=f"wait:question:{tool_id}",
                payload={"tool_id": tool_id},
                ttl_ms=0,  # 常驻等待泡（[DSH] D3）— dismissed on close
                now=now,
            )
        approval_keys = {f"wait:approval:{slot.get('id')}" for slot in approvals if slot.get("id")}
        for slot in approvals:
            slot_id = slot.get("id")
            if not slot_id:
                continue
            notifications.fire(
                conn,
                kind="wait_approval",
                rank=notifications.RANK_WAIT,
                dedup_key=f"wait:approval:{slot_id}",
                payload={"tool": slot.get("tool")},
                ttl_ms=0,
                now=now,
            )
        # resolved slots → close their standing notifications
        live_keys = {f"wait:question:{t}" for t in question_ids} | approval_keys
        for item in notifications.pending(conn, now=now):
            key = item["dedup_key"]
            if item["kind"] in ("wait_input", "wait_approval") and key not in live_keys:
                notifications.dismiss(conn, key, now=now)
    except Exception as exc:  # noqa: BLE001 - observability must not break polling
        log.warning("wait notification sync skipped: %s", type(exc).__name__)


def wait_state(conn: sqlite3.Connection | None, *, now: int | None = None, home: str | Path | None = None) -> dict[str, Any]:
    """GET /wait-state payload: ``{question_slots, approval_slots, fired_dedup_keys}``."""
    ts = now_ms() if now is None else int(now)
    approvals = approval_slots(home)
    if conn is not None:
        _sync_wait_notifications(conn, approvals, now=ts)
    return {
        "question_slots": question_slots(conn),
        "approval_slots": approvals,
        "fired_dedup_keys": notifications.active_dedup_keys(conn, now=ts),
    }
