"""Notifications REST surface (Goal pass — P0-2): the desktop half's consumer
endpoint for the rules-engine notification table.

    GET  /notifications          → {notifications: [pending()], fired_dedup_keys}
    POST /notifications/dismiss  → {dedup_key, dismissed}   (loopback-guarded)

Read-only JSON views; money fields inside ``payload_json`` already carry the
DATA_MODEL §8.1 class prefixes at fire time (rules.py), and the standing
CON-03 naming lint runs over these responses in tests.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException

from . import notifications, security
from .clock import now_ms

router = APIRouter(prefix="/notifications")


@router.get("")
def get_notifications() -> dict[str, Any]:
    """Pending (unexpired, un-dismissed) notifications, rank-ordered.

    ``wait_input`` / ``wait_approval`` kinds are intentionally INCLUDED here —
    they carry the same persistence as the wait-state slots, but the desktop
    half surfaces waiting via GET /wait-state (sticky bubbles) and must SKIP
    these kinds when mapping notifications → bubbles to avoid double display.
    """
    from .api import _require_ledger  # lazy: shared runtime/fail-closed discipline

    rt = _require_ledger()
    ts = now_ms()
    items = notifications.pending(rt.conn, now=ts)
    return {
        "notifications": items,
        "fired_dedup_keys": [item["dedup_key"] for item in items],
        "now": ts,
    }


@router.post("/dismiss", dependencies=[Depends(security.verify_loopback)])
def post_dismiss(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Dismiss one notification by dedup_key (404 when absent/already dismissed)."""
    from .api import _require_ledger

    rt = _require_ledger()
    dedup_key = payload.get("dedup_key")
    if not isinstance(dedup_key, str) or not dedup_key or len(dedup_key) > notifications._MAX_DEDUP_KEY:
        raise HTTPException(status_code=422, detail="dedup_key must be a non-empty string")
    dismissed = notifications.dismiss(rt.conn, dedup_key)
    if not dismissed:
        raise HTTPException(status_code=404, detail="notification not found or already dismissed")
    return {"dedup_key": dedup_key, "dismissed": True}
