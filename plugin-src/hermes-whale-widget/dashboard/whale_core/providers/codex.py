"""OpenAI Codex subscription quota provider (5h Session + Weekly).

Integrates with Hermes native ``agent.account_usage`` to read published quota
windows, plan type, banked reset credits, and reset countdowns.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from ..clock import now_ms

log = logging.getLogger("codex_provider")

TEMPLATE: dict[str, Any] = {
    "id": "openai-codex",
    "name": "ChatGPT / Codex",
    "kind": "quota",
    "origins": ["https://chatgpt.com"],
}


class CodexProvider:
    id = "openai-codex"
    name = "ChatGPT / Codex"
    kind = "quota"
    template = TEMPLATE

    _cache_ttl_s = 60.0
    _last_fetch = 0.0
    _cached_result: Optional[dict[str, Any]] = None

    def fetch_quota(self, *, force_refresh: bool = False) -> dict[str, Any]:
        """Fetch and normalize Codex subscription quota."""
        now = time.monotonic()
        if not force_refresh and self._cached_result and (now - self._last_fetch < self._cache_ttl_s):
            return self._cached_result

        try:
            from agent.account_usage import fetch_account_usage
            snapshot = fetch_account_usage("openai-codex")
        except ModuleNotFoundError:
            # Running in isolated test environment without hermes-agent in sys.path
            return {
                "provider_id": self.id,
                "name": self.name,
                "kind": self.kind,
                "configured": False,
                "state": "unknown",
                "windows": [],
                "details": [],
                "fetched_at": now_ms(),
            }
        except Exception as exc:
            log.warning("Codex quota fetch failed: %s", exc)
            return {
                "provider_id": self.id,
                "name": self.name,
                "kind": self.kind,
                "configured": False,
                "state": "unknown",
                "windows": [],
                "details": [f"Fetch error: {exc}"],
                "fetched_at": now_ms(),
            }

        if snapshot is None or not getattr(snapshot, "available", False):
            reason = getattr(snapshot, "unavailable_reason", None) or "Not configured"
            res = {
                "provider_id": self.id,
                "name": self.name,
                "kind": self.kind,
                "configured": False,
                "state": "unknown",
                "unavailable_reason": reason,
                "windows": [],
                "details": [],
                "fetched_at": now_ms(),
            }
            self._cached_result = res
            self._last_fetch = now
            return res

        windows = []
        for w in getattr(snapshot, "windows", ()) or ():
            used = getattr(w, "used_percent", None)
            used_pct = None if used is None else max(0.0, min(100.0, float(used)))
            rem_pct = None if used_pct is None else max(0.0, min(100.0, 100.0 - used_pct))
            reset_dt = getattr(w, "reset_at", None)
            reset_iso = reset_dt.isoformat() if hasattr(reset_dt, "isoformat") else None
            windows.append({
                "label": str(getattr(w, "label", "") or "Window"),
                "used_percent": used_pct,
                "remaining_percent": rem_pct,
                "reset_at": reset_iso,
                "detail": getattr(w, "detail", None),
            })

        res = {
            "provider_id": self.id,
            "name": self.name,
            "kind": self.kind,
            "configured": True,
            "state": "ok",
            "plan": getattr(snapshot, "plan", None),
            "windows": windows,
            "details": list(getattr(snapshot, "details", ()) or ()),
            "fetched_at": now_ms(),
        }
        self._cached_result = res
        self._last_fetch = now
        return res
