"""Shared fixtures (TEST_PLAN §2.3): tmp HERMES_HOME, production-style import
of plugin_api.py, TestClient with the router mounted exactly like the server.

Tests never touch the real data directory — HERMES_HOME is injected per test.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

DASHBOARD_DIR = Path(__file__).resolve().parents[1]
PLUGIN_API_PATH = DASHBOARD_DIR / "plugin_api.py"
PLUGIN_MODULE_NAME = "hermes_dashboard_plugin_whale-widget"
MOUNT_PREFIX = "/api/plugins/whale-widget"

# collection-time bootstrap: test modules import whale_core at module scope,
# and conftest.py is imported before any of them
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))


@pytest.fixture()
def hermes_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Temp HERMES_HOME per test (whale-widget/ created on demand inside)."""
    home = tmp_path / "hermes-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home


@pytest.fixture(scope="session")
def plugin_api():
    """Import plugin_api.py BY PATH exactly as web_server_dashboard.py does."""
    if str(DASHBOARD_DIR) not in sys.path:
        sys.path.insert(0, str(DASHBOARD_DIR))
    spec = importlib.util.spec_from_file_location(PLUGIN_MODULE_NAME, PLUGIN_API_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {PLUGIN_API_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PLUGIN_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def client(plugin_api, hermes_home):
    """Fresh TestClient per test: runtime reset + loopback override applied."""
    from whale_core import api as whale_api
    from whale_core import security as whale_security

    whale_api.reset_runtime()
    app = FastAPI()
    app.include_router(plugin_api.router, prefix=MOUNT_PREFIX)
    # L2 convention (TEST_PLAN §1.2): auth/loopback dependencies are overridden
    app.dependency_overrides[whale_security.verify_loopback] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    whale_api.reset_runtime()


@pytest.fixture()
def client_strict_loopback(plugin_api, hermes_home):
    """TestClient WITHOUT the loopback override (write endpoints must 403)."""
    from whale_core import api as whale_api

    whale_api.reset_runtime()
    app = FastAPI()
    app.include_router(plugin_api.router, prefix=MOUNT_PREFIX)
    with TestClient(app) as test_client:
        yield test_client
    whale_api.reset_runtime()


def make_request(host: str) -> SimpleNamespace:
    """Minimal stand-in for starlette Request for verify_loopback unit tests."""
    return SimpleNamespace(client=SimpleNamespace(host=host))
