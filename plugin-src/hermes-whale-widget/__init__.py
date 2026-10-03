"""whale-widget — agent-half entry (unified package).

The real surface of this plugin is:

* the **desktop** half (``desktop/plugin.js``, built from ``desktop/src/``),
  loaded by the Hermes renderer runtime-loader;
* the **dashboard** half (``dashboard/plugin_api.py``), mounted at
  ``/api/plugins/whale-widget/`` inside each profile's ``hermes serve`` process.

The agent half is intentionally a no-op stub in M0 (mirrors the
``ai-usage-tracker`` ``__init__.py`` pattern). It exists so the plugin is a
well-formed directory plugin that ``plugins.enabled`` / ``hermes plugins
enable/disable`` can address by name.

TODO(M8): register the approval observation hooks here —
``pre_approval_request`` / ``post_approval_response`` (observer-only; kwargs
filtered to ``surface == 'gateway'``) implemented in ``whale_agent/approval_hook.py``,
writing ``<HERMES_HOME>/whale-widget/approval-state.json`` atomically.
Import layout is verified for M0: the loader imports this file as package
``hermes_plugins.<slug>`` with ``__path__`` bound to the plugin directory
(``hermes_cli/plugins_loader.py`` ``_load_directory_module``), so
``from .whale_agent import approval_hook`` will work.
"""

from __future__ import annotations


def register(ctx) -> None:  # noqa: ARG001 - contract signature requires the context
    """No agent-side contributions in M0 (approval hooks arrive in M8)."""
    # TODO(M8): from .whale_agent.approval_hook import register_approval_hooks
    #           register_approval_hooks(ctx)
    return None
