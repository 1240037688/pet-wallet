"""DeepSeek balance provider — first vendor template (track②, M4).

GET ``/user/balance`` with bearer auth. Response shape (documented upstream;
the DSH repo has an endpoint-retirement precedent, so every field read here is
defensive — missing pieces become ``None``, never 0, DATA_MODEL §2.5):

    {"is_available": bool, "balance_infos": [
        {"currency": "CNY", "total_balance": "110.00",
         "granted_balance": "10.00", "topped_up_balance": "100.00"}, ...]}

Multi-currency selection ([DSH] F1 semantics): first CNY entry with a
non-zero total → any non-zero entry → CNY → first entry.

All money goes through :func:`whale_core.pricing.to_units` (Decimal, 1e8
fixed point). Errors map to the base taxonomy; the raw response body stored
by the caller never contains the credential (asserted in tests).
"""

from __future__ import annotations

import json
from decimal import InvalidOperation
from typing import Any

import httpx

from .. import pricing
from ..clock import now_ms
from . import base, gateway

TEMPLATE: dict[str, Any] = {
    "id": "deepseek",
    "name": "DeepSeek",
    "kind": "balance",
    "balance": {
        "url": "https://api.deepseek.com/user/balance",
        "auth": "bearer",
        "json_path": "balance_infos",
        # field-verified against upstream docs 2026-10; NOT probed automatically
        "verified": "unverified-2026-10-03",
    },
    "origins": ["https://api.deepseek.com"],
    "note": "granted/topped_up absent = NULL, never 0 (DATA_MODEL §2.5)",
}

_URL = TEMPLATE["balance"]["url"]


def select_currency(infos: list[dict[str, Any]]) -> dict[str, Any] | None:
    """CNY>0 → any non-zero → CNY → first (pure function; unit-tested)."""
    if not infos:
        return None

    def total(entry: dict[str, Any]):
        try:
            return pricing.to_units(entry.get("total_balance"))
        except (pricing.PricingError, OverflowError, InvalidOperation):
            return None

    nonzero = [e for e in infos if (total(e) or 0) > 0]
    for pool in (nonzero, infos):
        for entry in pool:
            if entry.get("currency") == "CNY":
                return entry
    return nonzero[0] if nonzero else infos[0]


class DeepSeekProvider:
    id = "deepseek"
    template = TEMPLATE

    def fetch_balance(self, cred: dict[str, Any], *, transport: Any = None) -> dict[str, Any]:
        """Fetch + normalize one balance observation (raises base taxonomy)."""
        gateway.assert_allowed_origin(_URL, TEMPLATE["origins"])
        try:
            with base.open_client(transport) as client:
                resp = client.get(
                    _URL,
                    headers={"Authorization": f"Bearer {cred['key']}", "Accept": "application/json"},
                )
        except httpx.TimeoutException as exc:
            raise base.ProviderTimeout("balance request timed out") from exc
        except httpx.HTTPError as exc:
            raise base.ProviderNetworkError("balance request failed") from exc
        base.raise_for_status(resp)
        try:
            data = resp.json()
        except ValueError as exc:
            raise base.ProviderBadResponse("balance response is not JSON") from exc
        if not isinstance(data, dict):
            raise base.ProviderBadResponse("balance response is not an object")

        infos = data.get("balance_infos")
        if not isinstance(infos, list) or not infos:
            raise base.ProviderBadResponse("balance_infos missing or empty")
        entry = select_currency(infos)
        if entry is None or not isinstance(entry, dict):
            raise base.ProviderBadResponse("balance_infos entries are unusable")
        try:
            balance_units = pricing.to_units(entry.get("total_balance"))
        except (pricing.PricingError, OverflowError, InvalidOperation) as exc:
            raise base.ProviderBadResponse("total_balance is not a number") from exc

        def optional(field: str) -> int | None:
            raw = entry.get(field)
            if raw is None or raw == "":
                return None
            try:
                return pricing.to_units(raw)
            except (pricing.PricingError, OverflowError, InvalidOperation):
                return None

        return {
            "provider_id": self.id,
            "scope": cred["fingerprint"],
            "currency": entry.get("currency") or "CNY",
            "observed_balance_units": balance_units,
            "granted_units": optional("granted_balance"),
            "topped_up_units": optional("topped_up_balance"),
            "fetched_at": now_ms(),
            # raw body for the snapshot row — no credential ever enters it
            "raw": {"is_available": data.get("is_available"), "balance_infos": infos},
        }


def raw_response_guard(raw: dict[str, Any]) -> None:
    """Belt-and-braces: refuse credential-shaped content in stored bodies."""
    from ..security import assert_no_secrets_in_payload

    assert_no_secrets_in_payload(raw)
