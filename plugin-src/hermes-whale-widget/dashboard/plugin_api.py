"""whale-widget dashboard backend — mounted at ``/api/plugins/whale-widget/``.

THIN IMPORT SHELL ONLY. The Hermes web server imports this file BY PATH
(``hermes_cli/web_server_dashboard.py`` ``_mount_plugin_api_routes``:
``importlib.util.spec_from_file_location("hermes_dashboard_plugin_<name>", ...)``),
so this module is not part of a package — it bootstraps ``sys.path`` with its
own directory and re-exports the router built by ``whale_core.api``.

Import contract (verified M0 against the local Hermes source):
  * a module-level ``router`` attribute is required;
  * trust gates: only bundled/user plugin sources, and the plugin must be in
    the ``plugins.enabled`` allow-list, else the backend is never imported;
  * the server mounts the router with prefix ``/api/plugins/<name>/``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_DASHBOARD_DIR = Path(__file__).resolve().parent
if str(_DASHBOARD_DIR) not in sys.path:
    # bootstrap so `import whale_core` resolves for both the serve process and
    # the by-path import; keep insertion order stable across re-imports.
    sys.path.insert(0, str(_DASHBOARD_DIR))

from whale_core.api import router  # noqa: E402  (needs the bootstrap above)

__all__ = ["router"]
