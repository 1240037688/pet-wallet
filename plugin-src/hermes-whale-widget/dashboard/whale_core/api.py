"""FastAPI router factory for the whale-widget dashboard half (M0).

The thin import shell lives in ``dashboard/plugin_api.py`` (imported BY PATH by
the Hermes web server — ``hermes_cli/web_server_dashboard.py``
``_mount_plugin_api_routes``); everything real lives here so it is testable
with FastAPI's TestClient without a serve process (TEST_PLAN L2).

Mount contract (verified against the local Hermes source, M0 probe):
  * module must expose a module-level ``router: APIRouter``;
  * the server mounts it at ``/api/plugins/<plugin-name>/``;
  * a per-request profile scope dependency wraps every route — the data
    directory therefore resolves per-profile through ``config.data_dir()``.

M0 endpoints: /health, /meta, /config (GET/PUT). Business endpoints land in
M1-M8 (IMPLEMENTATION_PLAN §3.4 REST contract table).

Runtime initialisation is LAZY (first request): importing this module must
have no side effects, so tests never touch a real data directory. Logging,
SQLite open + migration all happen in :func:`_ensure_runtime`.
"""

from __future__ import annotations

import json
import threading
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from . import config, db, migrations, security
from .logging_setup import get_logger, setup_logging

log = get_logger("api")

PLUGIN_NAME = "whale-widget"

router = APIRouter()

_DASHBOARD_DIR = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Lazy runtime (logging + db + schema)
# --------------------------------------------------------------------------

class _Runtime:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.started = False
        self.data_dir: Path | None = None
        self.conn = None
        self.schema_version = 0
        self.ledger_error: str | None = None


_rt = _Runtime()


def _ensure_runtime() -> _Runtime:
    with _rt.lock:
        if _rt.started:
            return _rt
        _rt.data_dir = config.data_dir()
        setup_logging(_rt.data_dir, also_stderr=False)
        try:
            _rt.conn = db.connect(_rt.data_dir / "whale.db")
            _rt.schema_version = migrations.migrate(_rt.conn)
        except db.LedgerCorruptError as exc:
            _rt.conn = None
            _rt.schema_version = 0
            _rt.ledger_error = str(exc)
        _rt.started = True
        log.info(
            "whale-widget runtime started: data_dir=%s schema_version=%s ledger_error=%s",
            _rt.data_dir, _rt.schema_version, _rt.ledger_error,
        )
        return _rt


def reset_runtime() -> None:
    """Test/reload hook: close handles and force re-initialisation."""
    with _rt.lock:
        if _rt.conn is not None:
            try:
                _rt.conn.close()
            except Exception as exc:  # noqa: BLE001 - never block reset
                log.warning("reset_runtime: closing db handle failed: %s", exc)
        _rt.conn = None
        _rt.started = False
        _rt.schema_version = 0
        _rt.ledger_error = None


def _manifest() -> dict[str, Any]:
    path = _DASHBOARD_DIR / "manifest.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"name": PLUGIN_NAME}


def _plugin_version() -> str:
    return str(_manifest().get("version", "0.0.0"))


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------

@router.get("/health")
def health() -> dict[str, Any]:
    """Mount probe (REST contract table §3.4, CON-00)."""
    rt = _ensure_runtime()
    payload: dict[str, Any] = {
        "ok": rt.ledger_error is None,
        "plugin": PLUGIN_NAME,
        "version": _plugin_version(),
        # own schema version (whale_meta), NOT Hermes state.db's
        "schema_version": rt.schema_version,
        # track③ (read-only state.db cross-check) arrives in M2
        "track3_state": "not_implemented",
        "contract_probe": None,
    }
    if rt.ledger_error is not None:
        payload["ledger_error"] = rt.ledger_error  # fail-closed surface, DATA_MODEL §7.4
    return payload


@router.get("/meta")
def meta() -> dict[str, Any]:
    """Plugin metadata endpoint (dashboard half self-description)."""
    manifest = _manifest()
    rt = _ensure_runtime()
    return {
        "name": manifest.get("name", PLUGIN_NAME),
        "label": manifest.get("label", PLUGIN_NAME),
        "description": manifest.get("description"),
        "version": manifest.get("version"),
        "api": manifest.get("api", "plugin_api.py"),
        "schema_version": rt.schema_version,
        "mounted_at": f"/api/plugins/{manifest.get('name', PLUGIN_NAME)}",
    }


@router.get("/config")
def get_config() -> dict[str, Any]:
    """Merged (defaults + config.json) view. Contains no credential fields by construction."""
    _ensure_runtime()
    return config.load_config()


@router.put("/config", dependencies=[Depends(security.verify_loopback)])
def put_config(update: dict[str, Any]) -> dict[str, Any]:
    """Whitelist-validated config write (loopback-guarded; full write gating in M12)."""
    _ensure_runtime()
    try:
        merged = config.save_config(update)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return merged
