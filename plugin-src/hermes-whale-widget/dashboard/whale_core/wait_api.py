"""Wait-event + wait-state REST surface (M8) — separate APIRouter.

Cross-package contract (consumed defensively by the desktop half, WP-1):

* ``POST /ingest/wait-event`` — the desktop half forwards clarify
  ``tool.start``/``tool.complete`` as ``{kind:'question', phase:'open'|'close',
  tool_id, session_id}``. Strict whitelist validation (unknown fields, unknown
  kinds/phases, bad types → 400): the payload can never smuggle answer content
  or secrets into the ledger. Loopback-guarded like every write endpoint.
  ``open`` records the slot (``whale_meta`` key ``wait.question.<tool_id>``)
  and fires the persistent ``wait_input`` notification
  (dedup ``wait:question:<tool_id>`` — one ring per pending question, DR-14);
  ``close`` removes the slot and dismisses the notification (等待解除收泡).
* ``GET /wait-state`` — ``{question_slots, approval_slots, fired_dedup_keys}``
  (approval slots merged from ``approval-state.json`` via
  :mod:`whale_core.wait_bridge`; ``fired_dedup_keys`` = active notification
  dedup keys for reload alignment).

This router is mounted by ``whale_core/api.py`` with a single
``router.include_router(wait_api.router)`` line; it reaches the shared lazy
runtime through a function-level import (the module must stay importable
without pulling api.py at load time).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from . import notifications, security, wait_bridge
from .clock import now_ms
from .logging_setup import get_logger

log = get_logger("wait_api")

router = APIRouter()

ALLOWED_KINDS = ("question",)
ALLOWED_PHASES = ("open", "close")
ALLOWED_FIELDS = frozenset({"kind", "phase", "tool_id", "session_id"})
_MAX_ID_LEN = 256


class WaitEventError(ValueError):
    """Invalid wait-event payload → HTTP 400 (messages name fields, not values)."""


def validate_wait_event(payload: Any) -> dict[str, str]:
    """Strict whitelist validation. Returns ``{kind, phase, tool_id, session_id}``."""
    if not isinstance(payload, dict):
        raise WaitEventError("wait-event payload must be a JSON object")
    unknown = sorted(k for k in payload if k not in ALLOWED_FIELDS)
    if unknown:
        raise WaitEventError(f"wait-event payload has unknown field(s): {', '.join(unknown)}")
    kind = payload.get("kind")
    if kind not in ALLOWED_KINDS:
        raise WaitEventError("wait-event payload invalid: kind must be 'question'")
    phase = payload.get("phase")
    if phase not in ALLOWED_PHASES:
        raise WaitEventError("wait-event payload invalid: phase must be 'open'|'close'")
    for field in ("tool_id", "session_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value or len(value) > _MAX_ID_LEN:
            raise WaitEventError(f"wait-event payload invalid: {field} must be a non-empty string (<=256)")
    return {"kind": kind, "phase": phase, "tool_id": payload["tool_id"], "session_id": payload["session_id"]}


def _runtime():
    """Shared lazy runtime (function-level import keeps the module cycle-free)."""
    from . import api as whale_api

    return whale_api._require_ledger()


@router.post("/ingest/wait-event", dependencies=[Depends(security.verify_loopback)])
def post_wait_event(payload: Any = Body(...)) -> dict[str, Any]:
    """Question pending/clear report (clarify tool lifecycle forward, WP-1)."""
    rt = _runtime()
    try:
        event = validate_wait_event(payload)
        security.assert_no_secrets_in_payload(event)
    except (WaitEventError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    ts = now_ms()
    if event["phase"] == "open":
        slot = wait_bridge.record_question_slot(
            rt.conn, tool_id=event["tool_id"], session_id=event["session_id"], now=ts,
        )
        try:
            status = notifications.fire(
                rt.conn,
                kind="wait_input",
                rank=notifications.RANK_WAIT,
                dedup_key=f"wait:question:{event['tool_id']}",
                payload={"tool_id": event["tool_id"], "session_id": event["session_id"]},
                ttl_ms=0,
                now=ts,
            )
        except Exception as exc:  # noqa: BLE001 - slot recording must not fail on notification errors
            log.warning("wait_input notification skipped: %s", type(exc).__name__)
            status = "skipped"
        return {"status": "accepted", "phase": "open", "slot": slot, "notification": status}

    removed = wait_bridge.clear_question_slot(rt.conn, tool_id=event["tool_id"])
    try:
        dismissed = notifications.dismiss(rt.conn, f"wait:question:{event['tool_id']}", now=ts)
    except Exception as exc:  # noqa: BLE001
        log.warning("wait_input dismissal skipped: %s", type(exc).__name__)
        dismissed = False
    return {"status": "accepted", "phase": "close", "removed": bool(removed), "dismissed": bool(dismissed)}


@router.get("/wait-state")
def get_wait_state() -> dict[str, Any]:
    """Merged waiting surface (contract: question_slots/approval_slots/fired_dedup_keys)."""
    from . import api as whale_api

    rt = whale_api._ensure_runtime()
    return wait_bridge.wait_state(rt.conn)
