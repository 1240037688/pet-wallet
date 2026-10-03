"""whale_agent — agent-half package (approval observation hooks).

STUB (M0). ``approval_hook.py`` arrives in M8: registers
``pre_approval_request`` / ``post_approval_response`` (observer-only), filters
kwargs to ``surface == 'gateway'``, atomically writes
``<HERMES_HOME>/whale-widget/approval-state.json``.

Import layout verified in M0: the Hermes loader imports the plugin's
``__init__.py`` as package ``hermes_plugins.<slug>`` with ``__path__`` bound to
the plugin directory (``hermes_cli/plugins_loader.py`` ``_load_directory_module``),
so ``from .whale_agent.approval_hook import ...`` works from the agent half.
"""

from __future__ import annotations  # noqa: F401  (stub package — implemented in M8)
