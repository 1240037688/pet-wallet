"""whale_core — the only business-logic area of the whale-widget dashboard half.

Loaded via a ``sys.path`` bootstrap from ``dashboard/plugin_api.py`` (the Hermes
web server imports that file by path, not as a package — see
``hermes_cli/web_server_dashboard.py`` ``_mount_plugin_api_routes``), so this
package must never assume a parent package context.

Module map (IMPLEMENTATION_PLAN §3.1):
    config.py         data dir + config.json (M0)
    logging_setup.py  rotating log + redaction filter (M0)
    db.py             SQLite connection, WAL, fail-closed (M0)
    migrations.py     schema migrations v1 = DATA_MODEL §7.2 DDL (M0)
    security.py       loopback guard + REST naming lint helpers (M0)
    api.py            FastAPI router factory (M0; thin shell lives in plugin_api.py)
    ingest.py         M1 stub → M2 implementation
    usage_ledger.py   M2/M3
    pricing.py        M3
    balance_ledger.py M4
    providers/        M4/M11
    rules.py          M8
    wait_bridge.py    M8
    notifications.py  M7/M8
    track3.py         M2 (optional read-only state.db cross-check)
    archive.py        M2
"""

from __future__ import annotations

__all__ = [
    "config",
    "logging_setup",
    "db",
    "migrations",
    "security",
]
