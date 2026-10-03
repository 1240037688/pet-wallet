"""Credential gateway — secret resolution, fingerprints, outbound whitelist (M4).

Secrets exist ONLY in this half (ARCHITECTURE_DECISION DR-3):

* resolution order for a provider id:
  1. Hermes profile-scoped secret — ``agent.secret_scope.get_secret(ENV_NAME)``
     (verified against local hermes-agent ``agent/secret_scope.py:219``; the
     dashboard half runs inside ``hermes serve`` so the import exists there).
     Any import/scope failure falls through, never crashes the caller.
  2. process env for the same name (single-profile deployments).
  3. ``<data_dir>/credentials.json`` fallback — user-created, plugin NEVER
     writes it (INSTALL.md documents the plaintext risk; AGENTS.md §7).
* outside world sees only ``{provider_id, configured, source, credential_id,
  fingerprint}`` — never the key (REST responses, logs, tests all assert this).
* outbound rule ([DSH] F2): credentials may only be sent to template-pinned
  origins (:func:`assert_allowed_origin`) — "edit config = exfiltrate key" is
  structurally impossible for template providers.
"""

from __future__ import annotations

import hashlib
import json
import os
from urllib.parse import urlsplit
from typing import Any

from .. import config
from ..logging_setup import get_logger

log = get_logger("gateway")

# provider_id -> conventional Hermes/ENV secret name
CREDENTIAL_ENV = {
    "deepseek": "DEEPSEEK_API_KEY",
}

CREDENTIALS_FILENAME = "credentials.json"


def fingerprint(key: str) -> str:
    """``sha256(key)[:24]`` — the track② scope (ledger books are per-key)."""
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def resolve_credential(provider_id: str) -> dict[str, Any] | None:
    """Resolve a credential or ``None`` (never raises; never logs the key)."""
    key: str | None = None
    source = "none"
    env_name = CREDENTIAL_ENV.get(provider_id)
    if env_name:
        key = _secret_via_hermes(env_name) or os.environ.get(env_name)
        if key:
            source = "hermes_secret"
    if not key:
        key = _key_from_credentials_file(provider_id)
        if key:
            source = "credentials_file"
    if not key:
        return None
    fp = fingerprint(key)
    return {
        "provider_id": provider_id,
        "name": provider_id,
        "credential_id": f"{provider_id}:{fp[:8]}",
        "fingerprint": fp,
        "key": key,
        "source": source,
    }


def credential_status(provider_id: str) -> dict[str, Any]:
    """REST-safe credential view — the ONLY credential shape allowed to leave."""
    cred = resolve_credential(provider_id)
    if cred is None:
        return {"provider_id": provider_id, "configured": False, "source": "none"}
    return {
        "provider_id": provider_id,
        "configured": True,
        "source": cred["source"],
        "credential_id": cred["credential_id"],
        "fingerprint": cred["fingerprint"],
    }


def assert_allowed_origin(url: str, allowed_origins: list[str]) -> None:
    """Refuse any credential-bearing request to a non-pinned origin ([DSH] F2)."""
    origin = f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
    if origin not in allowed_origins:
        raise ValueError(f"outbound origin not allowed for credential use: {origin}")


def _secret_via_hermes(env_name: str) -> str | None:
    """Profile-scoped read via the serve process's agent package (guarded)."""
    try:
        from agent.secret_scope import get_secret  # type: ignore

        value = get_secret(env_name)
        return value if isinstance(value, str) and value else None
    except Exception:  # noqa: BLE001 - not in serve / multiplex scope issues / absent
        return None


def _key_from_credentials_file(provider_id: str) -> str | None:
    path = config.data_dir() / CREDENTIALS_FILENAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("credentials.json unreadable (ignored): %s", type(exc).__name__)
        return None
    if not isinstance(data, dict):
        return None
    providers = data.get("providers") if isinstance(data.get("providers"), dict) else data
    key = providers.get(provider_id)
    if isinstance(key, dict):
        key = key.get("api_key")
    return key if isinstance(key, str) and key else None
