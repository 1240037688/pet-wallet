"""whale-widget — agent-half entry (unified package).

The real surface of this plugin is:

* the **desktop** half (``desktop/plugin.js``, built from ``desktop/src/``),
  loaded by the Hermes renderer runtime-loader;
* the **dashboard** half (``dashboard/plugin_api.py``), mounted at
  ``/api/plugins/whale-widget/`` inside each profile's ``hermes serve`` process;
* the **agent** half (M8): observer-only approval hooks, registered here
  following the real-plugin pattern (hermes-lcm ``__init__.py:448-453``):
  ``ctx.register_hook(name, callback)`` with ``getattr`` guard. The hooks write
  ``<HERMES_HOME>/whale-widget/approval-state.json`` (ids + timestamp only,
  atomically) — they never veto, pre-answer, or touch approval content.

Registration is wrapped end-to-end: a failed or missing hook registration is
logged and swallowed so the plugin still loads and the agent's approval flow is
untouched (the loader rolls back the whole plugin on a raising ``register``).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def register(ctx) -> None:
    """Register the approval observation hooks (M8); never raises."""
    try:
        from .whale_agent.approval_hook import register_approval_hooks

        register_approval_hooks(ctx)
    except Exception as exc:  # noqa: BLE001 - hook failure must not fail the plugin
        logger.warning("whale-widget agent half: approval hook registration skipped: %s", type(exc).__name__)
    return None
