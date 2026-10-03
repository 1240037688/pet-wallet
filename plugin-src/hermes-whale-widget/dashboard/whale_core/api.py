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

M0 endpoints: /health, /meta, /config (GET/PUT). M2 adds the track① surface:
POST /ingest/turn (idempotent settlement), GET /usage/summary, GET /usage/turns.

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

from fastapi import APIRouter, Body, Depends, HTTPException

from . import archive, balance_ledger, config, db, ingest, migrations, poller, pricing, security, usage_ledger, wait_api
from .clock import now_ms
from .logging_setup import get_logger, setup_logging

log = get_logger("api")

PLUGIN_NAME = "whale-widget"

router = APIRouter()
router.include_router(wait_api.router)  # M8: /ingest/wait-event + /wait-state (cross-package contract)

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
        poller.ensure_started(_rt)
        return _rt


def reset_runtime() -> None:
    """Test/reload hook: close handles and force re-initialisation."""
    poller.stop()
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


# --------------------------------------------------------------------------
# M2: idempotent ingest + track① usage queries
# --------------------------------------------------------------------------

def _require_ledger() -> Any:
    """Shared write-path connection or 503 (fail-closed, DATA_MODEL §7.4)."""
    rt = _ensure_runtime()
    if rt.conn is None:
        raise HTTPException(status_code=503, detail="ledger unavailable (fail-closed)")
    return rt


@router.post("/ingest/turn", dependencies=[Depends(security.verify_loopback)])
def post_ingest_turn(payload: Any = Body(...)) -> dict[str, Any]:
    """Idempotent turn settlement (REST contract table; CON-01).

    Accepts a single turn object or ``{"turns": [...]}`` (max 100). Response:
    ``{status: 'accepted'|'duplicate', accepted, duplicate[, aligned][, skipped]}``.
    Invalid payloads → 400 with a field-level message that never echoes values.
    """
    rt = _require_ledger()
    try:
        if isinstance(payload, dict) and "turns" in payload:
            if not isinstance(payload["turns"], list):
                raise ingest.IngestError("ingest payload invalid: turns must be a list")
            result = ingest.ingest_batch(rt.conn, payload["turns"])
        else:
            result = ingest.ingest_turn(rt.conn, payload)
    except ingest.IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    # opportunistic retention prune (single-writer; guarded to once per day)
    try:
        archive.maybe_daily_tick(rt.conn)
    except Exception:  # noqa: BLE001 - prune must never fail the ingest
        pass
    return result


@router.get("/usage/summary")
def get_usage_summary(days: int = 7) -> dict[str, Any]:
    """Today + trailing-``days`` rollup, per-model split, partial flags (CON-02)."""
    rt = _require_ledger()
    if days < 1 or days > 366:
        raise HTTPException(status_code=400, detail="days must be between 1 and 366")
    return usage_ledger.usage_summary(rt.conn, days=days)


@router.get("/usage/turns")
def get_usage_turns(limit: int = usage_ledger.DEFAULT_TURNS_LIMIT, session_id: str | None = None) -> dict[str, Any]:
    """Most recent settled turns (bubble/detail data source; CON-02)."""
    rt = _require_ledger()
    if limit < 1 or limit > usage_ledger.MAX_TURNS_LIMIT:
        raise HTTPException(status_code=400, detail=f"limit must be between 1 and {usage_ledger.MAX_TURNS_LIMIT}")
    return usage_ledger.usage_turns(rt.conn, limit=limit, session_id=session_id)


# --------------------------------------------------------------------------
# M3: pricing surface (overview + custom overrides)
# --------------------------------------------------------------------------

@router.get("/pricing")
def get_pricing() -> dict[str, Any]:
    """Built-in + custom price tables (never any secret; CON-02 naming)."""
    rt = _require_ledger()
    return pricing.pricing_overview(rt.conn)


@router.put("/pricing/custom", dependencies=[Depends(security.verify_loopback)])
def put_pricing_custom(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Set (``pricing`` object) or clear (``pricing: null``) a custom model price.

    Custom prices replace the whole quote for the matched key and freeze into
    future turn snapshots (DATA_MODEL §2.2); history is never rewritten.
    """
    rt = _require_ledger()
    model = payload.get("model")
    quote = payload.get("pricing")
    if not isinstance(model, str) or not model.strip():
        raise HTTPException(status_code=422, detail="model must be a non-empty string")
    if quote is not None and not isinstance(quote, dict):
        raise HTTPException(status_code=422, detail="pricing must be an object or null")
    try:
        pricing.set_custom_price(rt.conn, model, quote, now=now_ms())
    except (pricing.PricingError, OverflowError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return {"model": model.strip(), "pricing": quote, "custom": pricing.pricing_overview(rt.conn)["custom"]}


# --------------------------------------------------------------------------
# M4: track② balance surface (state machine + summary + manual ops)
# --------------------------------------------------------------------------

@router.get("/balance")
def get_balance() -> dict[str, Any]:
    """Five-state balance view (unknown/zero/error/stale/ok; DATA_MODEL §6).

    API failure never masquerades as zero: error/stale states carry the last
    known ``observed_balance_units`` plus the error kind.
    """
    rt = _require_ledger()
    return balance_ledger.balance_state(rt.conn)


@router.get("/balance/summary")
def get_balance_summary(days: int = 7) -> dict[str, Any]:
    """Track② trailing-days rollup (observed_spend / credit / partial flags)."""
    rt = _require_ledger()
    if days < 1 or days > 366:
        raise HTTPException(status_code=400, detail="days must be between 1 and 366")
    return balance_ledger.balance_summary(rt.conn, days=days)


@router.post("/balance/refresh", dependencies=[Depends(security.verify_loopback)])
def post_balance_refresh() -> dict[str, Any]:
    """Manual refresh bypassing the poller cadence (sync; error states in-band)."""
    rt = _require_ledger()
    return balance_ledger.refresh_balance(rt.conn)


@router.post("/balance/adjustment", dependencies=[Depends(security.verify_loopback)])
def post_balance_adjustment(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """Explicit correction (implied-usage formula); revision mismatch → 409."""
    rt = _require_ledger()
    day = payload.get("day")
    if not isinstance(day, str) or len(day) != 10:
        raise HTTPException(status_code=422, detail="day must be an ISO date string")
    credits = payload.get("credits_units", 0)
    other_debits = payload.get("other_debits_units", 0)
    revision = payload.get("revision")
    if not isinstance(credits, int) or isinstance(credits, bool) or credits < 0:
        raise HTTPException(status_code=422, detail="credits_units must be a non-negative integer")
    if not isinstance(other_debits, int) or isinstance(other_debits, bool) or other_debits < 0:
        raise HTTPException(status_code=422, detail="other_debits_units must be a non-negative integer")
    if revision is not None and not isinstance(revision, str):
        raise HTTPException(status_code=422, detail="revision must be a string or null")
    scope = balance_ledger.gateway.credential_status(balance_ledger.DEFAULT_PROVIDER_ID).get("fingerprint")
    if scope is None:
        raise HTTPException(status_code=400, detail="no credential configured for track②")
    currency_row = rt.conn.execute(
        "SELECT currency FROM daily_summary WHERE scope=? AND day=? AND track='balance'",
        (scope, day),
    ).fetchone()
    if currency_row is None:
        raise HTTPException(status_code=404, detail="no balance observations recorded for that day")
    try:
        result = balance_ledger.apply_adjustment(
            rt.conn, scope=scope, day=day, currency=currency_row["currency"],
            credits_units=credits, other_debits_units=other_debits, revision=revision,
        )
    except balance_ledger.AdjustmentConflict:
        raise HTTPException(status_code=409, detail="revision mismatch; re-fetch and retry") from None
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    return result
