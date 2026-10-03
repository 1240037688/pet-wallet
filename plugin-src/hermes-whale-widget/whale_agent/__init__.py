"""whale_agent — agent-half package (approval observation hooks, M8).

``approval_hook.py`` registers ``pre_approval_request`` / ``post_approval_response``
as observer-only hooks (return values ignored by the host; plugins cannot veto
or pre-answer), filtered to ``surface == 'gateway'``, atomically writing
``<HERMES_HOME>/whale-widget/approval-state.json`` (entries carry ids and a
timestamp only — never approval content). Consumed by
``whale_core.wait_bridge`` → GET /wait-state.

Import layout verified in M0: the Hermes loader imports the plugin's
``__init__.py`` as package ``hermes_plugins.<slug>`` with ``__path__`` bound to
the plugin directory (``hermes_cli/plugins_loader.py`` ``_load_directory_module``),
so ``from .whale_agent.approval_hook import ...`` works from the agent half.

This module is loaded by path in tests (no relative imports inside
``approval_hook.py``).
"""

from __future__ import annotations  # noqa: F401  (marker: package doc only)
