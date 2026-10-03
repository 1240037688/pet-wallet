"""Approval observation hooks (agent half, M8) — observer-only bridge.

Registered from the plugin root ``__init__.py`` via
``register_approval_hooks(ctx)`` and wired with ``ctx.register_hook`` — the
same defensive pattern as the real hermes-lcm plugin (``__init__.py:448-453``).
Probe conclusions (local Hermes source, read-only; recorded in WORKLOG):

* ``hermes_cli/plugins.py:144-148`` — ``VALID_HOOKS`` contains
  ``pre_approval_request`` / ``post_approval_response``; **returns are
  ignored** — plugins cannot veto or pre-answer an approval;
* ``hermes_cli/plugins.py:974-976`` — registration API is
  ``ctx.register_hook(hook_name: str, callback: Callable) -> PluginRegistration``;
* fire sites ``tools/approval_gateway_wait.py:147-152,198`` (gateway surface)
  and ``tools/approval.py:912-917`` (CLI surface): kwargs are ``command,
  description, pattern_key, pattern_keys, session_key, surface`` plus
  ``choice``/``decided_by`` on the post hook; ``tools/approval_context.py:54-73``
  additionally injects ``turn_id`` / ``tool_call_id`` / ``session_id`` and
  guarantees the dispatch never raises.

Behaviour (WP-2 hard rules):

* only the ``gateway`` surface is observed (the desktop half watches gateway
  approvals; CLI panels answer in-terminal);
* the pending list is persisted to ``<data_dir>/approval-state.json`` as
  ``{"approvals": [{"id", "kind", "tool", "since"}]}`` — ids and a timestamp
  ONLY. The command/description text and every other kwarg are **never**
  written (no approval payload, no secrets);
* writes are atomic (tmp file + ``os.replace``) under a module lock — the
  dashboard half reads the same file from another thread;
* every callback and the registration itself are wrapped: any failure is
  logged and the agent's approval flow is untouched (observability is not
  safety-critical, mirroring ``approval_context._fire_approval_hook``);
* a corrupt state file is treated as empty (fail-open for a display surface)
  and atomically rewritten on the next event.

``whale_core.config.data_dir()`` is reused for the data directory when
importable (the dashboard half may not be loaded yet in the serve process —
the import is guarded and falls back to resolving ``<HERMES_HOME>/whale-widget``
directly).
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("whale_agent.approval_hook")

APPROVAL_STATE_FILENAME = "approval-state.json"
APPROVAL_KIND = "approval"
SURFACE_FILTER = "gateway"  # only gateway approvals surface in the desktop UI
MAX_ENTRIES = 32  # defensive cap; approvals are resolved (removed) quickly

_state_lock = threading.Lock()


# ---------------------------------------------------------------------------
# data dir + state file primitives
# ---------------------------------------------------------------------------

def _data_dir() -> Path:
    """``<HERMES_HOME>/whale-widget/`` — reuses whale_core.config when importable."""
    whale_config = None
    try:
        from whale_core import config as whale_config  # type: ignore[no-redef]
    except ImportError:
        dashboard_dir = str(Path(__file__).resolve().parents[1] / "dashboard")
        if dashboard_dir not in sys.path:
            sys.path.insert(0, dashboard_dir)
        try:
            from whale_core import config as whale_config  # type: ignore[no-redef]
        except ImportError:
            whale_config = None
    if whale_config is not None:
        return Path(whale_config.data_dir())
    home = Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))
    data = home / "whale-widget"
    data.mkdir(parents=True, exist_ok=True)
    return data


def state_path(home: str | Path | None = None) -> Path:
    """Path of the pending-approval state file (tests inject ``home``)."""
    if home is not None:
        return Path(home) / "whale-widget" / APPROVAL_STATE_FILENAME
    return _data_dir() / APPROVAL_STATE_FILENAME


def read_state(home: str | Path | None = None) -> list[dict[str, Any]]:
    """Pending approval entries; missing/corrupt file → ``[]``."""
    path = state_path(home)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        logger.warning("approval-state.json unreadable — treating as empty")
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("approvals"), list):
        return []
    return [entry for entry in raw["approvals"] if isinstance(entry, dict)]


def _write_state(path: Path, entries: list[dict[str, Any]]) -> None:
    """Atomic write (tmp + os.replace) — readers never see a torn file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"approvals": entries}, fh, ensure_ascii=False, sort_keys=True, indent=2)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# entry derivation (ids and timestamps only — never approval content)
# ---------------------------------------------------------------------------

def _slot_id(kwargs: dict[str, Any]) -> str:
    """Stable pre→post pairing id: ``<session>#<tool_call_id|turn_id|pending>``.

    Approval hooks fire pre and post with the same correlation kwargs
    (approval_context contextvars), so the same id pairs the pair; the empty
    correlation case falls back to a session-scoped slot (approvals block the
    session, so at most one unnamed slot is live — the post hook removes it by
    session prefix).
    """
    session = str(kwargs.get("session_key") or kwargs.get("session_id") or "")
    for key in ("tool_call_id", "turn_id"):
        value = str(kwargs.get(key) or "").strip()
        if value:
            return f"{session}#{value}"
    return f"{session}#pending"


def _entry_for(kwargs: dict[str, Any], now_ms: int) -> dict[str, Any]:
    slot_id = _slot_id(kwargs)
    return {
        "id": slot_id,
        "kind": APPROVAL_KIND,
        "tool": str(kwargs.get("tool_call_id") or ""),
        "since": int(now_ms),
    }


def add_entry(kwargs: dict[str, Any], *, now: int | None = None, home: str | Path | None = None) -> bool:
    """Record one pending approval (upsert by id). Returns True when written."""
    import time

    ts = int(now if now is not None else time.time() * 1000)
    entry = _entry_for(kwargs, ts)
    path = state_path(home)
    with _state_lock:
        entries = [e for e in read_state(home) if e.get("id") != entry["id"]]
        entries.append(entry)
        entries.sort(key=lambda e: int(e.get("since") or 0))
        if len(entries) > MAX_ENTRIES:  # drop oldest; approvals never accumulate
            entries = entries[-MAX_ENTRIES:]
        _write_state(path, entries)
    return True


def remove_entry(kwargs: dict[str, Any], *, home: str | Path | None = None) -> bool:
    """Remove the entry matching the response (exact id, session-prefix fallback)."""
    slot_id = _slot_id(kwargs)
    prefix = f"{slot_id.split('#', 1)[0]}#"
    path = state_path(home)
    with _state_lock:
        entries = read_state(home)
        remaining = [e for e in entries if e.get("id") != slot_id]
        if len(remaining) == len(entries) and prefix:
            # correlation ids absent on this surface: clear the session's slot
            remaining = [e for e in remaining if not str(e.get("id") or "").startswith(prefix)]
        if len(remaining) == len(entries):
            return False
        _write_state(path, remaining)
    return True


# ---------------------------------------------------------------------------
# hook callbacks (never raise) + registration
# ---------------------------------------------------------------------------

def _is_gateway_surface(kwargs: dict[str, Any]) -> bool:
    return str(kwargs.get("surface") or "") == SURFACE_FILTER


def _on_pre_approval_request(**kwargs: Any) -> None:
    """pre_approval_request observer: record the pending approval."""
    try:
        if not _is_gateway_surface(kwargs):
            return
        add_entry(kwargs)
        logger.debug("whale-widget: approval request observed (slot recorded)")
    except Exception as exc:  # noqa: BLE001 - observability must never break approvals
        logger.warning("whale-widget approval observation failed: %s", type(exc).__name__)


def _on_post_approval_response(**kwargs: Any) -> None:
    """post_approval_response observer: remove the resolved approval.

    Fires for every resolution (approve / deny / timeout / cancelled) — the
    waiting is over either way, so the slot always clears.
    """
    try:
        if not _is_gateway_surface(kwargs):
            return
        remove_entry(kwargs)
        logger.debug("whale-widget: approval response observed (slot cleared)")
    except Exception as exc:  # noqa: BLE001
        logger.warning("whale-widget approval observation failed: %s", type(exc).__name__)


HOOK_CALLBACKS: dict[str, Callable[..., None]] = {
    "pre_approval_request": _on_pre_approval_request,
    "post_approval_response": _on_post_approval_response,
}


def register_approval_hooks(ctx: Any) -> list[Any]:
    """Register both observers; returns the handles (empty when unavailable).

    Registration failure (missing/raising ``register_hook``) is logged and
    swallowed — the plugin must keep loading, the agent must keep approving.
    """
    handles: list[Any] = []
    register_hook = getattr(ctx, "register_hook", None)
    if not callable(register_hook):
        logger.info("whale-widget agent half: no register_hook on ctx — approval observations disabled")
        return handles
    for hook_name, callback in HOOK_CALLBACKS.items():
        try:
            handles.append(register_hook(hook_name, callback))
            logger.debug("whale-widget agent half: registered %s", hook_name)
        except Exception as exc:  # noqa: BLE001 - registration must not fail the plugin
            logger.warning("whale-widget agent half: %s registration failed: %s", hook_name, type(exc).__name__)
    return handles
