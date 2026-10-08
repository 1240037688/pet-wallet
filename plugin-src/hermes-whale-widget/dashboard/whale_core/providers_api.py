"""Provider status REST surface (WP-dashboard) — one router, two read endpoints.

* ``GET /providers/status`` — every known template provider (registry
  ``known_ids()``) merged with its credential status
  (:func:`providers.gateway.credential_status`) and, when configured, the
  five-state balance/quota view.
* ``GET /balance/all`` — the same rows, configured only: the pet-bubble data
  source (the desktop half joins it with ``config.bubble.balance_providers``,
  the show-list persisted by the dashboard page's show/hide toggles).

Row contract (WP-dashboard; optional fields are omitted when unknown):

    {provider_id, known, configured, source,
     credential_id?, fingerprint?, state?, observed_balance_units?, currency?,
     kind?, name?, plan?, windows?, details?}

No credential material ever leaves: ``credential_status`` is the only
credential shape allowed out (gateway DR-3), fingerprints are scope ids, and
an unconfigured row carries ``state='unknown'`` and NO credential fields.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from . import balance_ledger
from .logging_setup import get_logger
from .providers import gateway, registry

log = get_logger("providers_api")

router = APIRouter()


def provider_rows(conn, *, configured_only: bool = False) -> list[dict[str, Any]]:
    """WP-dashboard provider rows (registry × credential × balance/quota merge)."""
    rows: list[dict[str, Any]] = []
    for provider_id in registry.known_ids():
        provider = registry.get_provider(provider_id)
        is_quota = getattr(provider, "kind", None) == "quota"

        if is_quota:
            quota_data = provider.fetch_quota()
            configured = bool(quota_data.get("configured"))
            if configured_only and not configured:
                continue
            row: dict[str, Any] = {
                "provider_id": provider_id,
                "known": True,
                "configured": configured,
                "source": "codex_auth" if configured else "none",
                "state": quota_data.get("state", "unknown"),
            }
            if configured:
                row["kind"] = "quota"
                row["name"] = getattr(provider, "name", provider_id)
                row["plan"] = quota_data.get("plan")
                row["windows"] = quota_data.get("windows", [])
                row["details"] = quota_data.get("details", [])
            rows.append(row)
            continue

        cred = gateway.credential_status(provider_id)
        configured = bool(cred.get("configured"))
        if configured_only and not configured:
            continue
        row = {
            "provider_id": provider_id,
            "known": True,
            "configured": configured,
            "source": cred.get("source", "none"),
        }
        if configured:
            row["credential_id"] = cred.get("credential_id")
            row["fingerprint"] = cred.get("fingerprint")
            state = balance_ledger.balance_state(conn, provider_id=provider_id)
            row["state"] = state.get("state", "unknown")
            if state.get("observed_balance_units") is not None:
                row["observed_balance_units"] = int(state["observed_balance_units"])
            if state.get("currency") is not None:
                row["currency"] = state["currency"]
        else:
            row["state"] = "unknown"
        rows.append(row)
    return rows


@router.get("/providers/status")
def get_providers_status() -> dict[str, Any]:
    """All known providers with credential + balance/quota view."""
    from .api import _require_ledger  # lazy: shared runtime/fail-closed discipline

    rt = _require_ledger()
    return {"providers": provider_rows(rt.conn)}


@router.get("/balance/all")
def get_balance_all() -> dict[str, Any]:
    """Configured providers only — the pet-bubble balance data source."""
    from .api import _require_ledger  # lazy: shared runtime/fail-closed discipline

    rt = _require_ledger()
    return {"providers": provider_rows(rt.conn, configured_only=True)}
