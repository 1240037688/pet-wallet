"""Security helpers for the REST surface (M0).

* :func:`verify_loopback` — FastAPI dependency for WRITE endpoints: only
  loopback clients may mutate state (threat model: a remote client that can
  change config is one step from exfiltrating credentials — [DSH] F2).
  Tests override this dependency (TEST_PLAN §1.2).
* :func:`find_bare_money_keys` — [DM] §8.1 naming lint: REST responses must
  never expose bare ``cost`` / ``spend`` / ``used`` keys; every money field
  carries its class prefix (``estimated_*`` / ``observed_*`` / ``reported_*``
  / ``adjustment_*``) or an explicit ``*_units`` / ``basis`` companion.
* :func:`assert_no_secrets_in_payload` — recursive scan used by tests and
  (later, M2+) before persisting raw payloads: refuses ``sk-``/``Bearer``
  shapes in stored JSON.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Request

LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}

# Keys that may never appear bare in a REST payload (DATA_MODEL §8.1).
BARE_MONEY_KEYS = frozenset({"cost", "spend", "used"})

_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]{6,}", re.IGNORECASE)


def verify_loopback(request: Request) -> None:
    """Dependency: reject non-loopback clients on write endpoints with 403."""
    client = request.client
    host = client.host if client is not None else ""
    if host not in LOOPBACK_HOSTS:
        raise HTTPException(status_code=403, detail="write endpoints are loopback-only")


def find_bare_money_keys(payload: Any, _prefix: str = "") -> list[str]:
    """Recursively collect paths of bare ``cost``/``spend``/``used`` keys.

    Returns a list of dotted paths (empty = clean). Used by the contract tests
    as the standing REST naming lint (TEST_PLAN CON-03).
    """
    found: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{_prefix}.{key}" if _prefix else str(key)
            if str(key) in BARE_MONEY_KEYS:
                found.append(path)
            found.extend(find_bare_money_keys(value, path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            found.extend(find_bare_money_keys(item, f"{_prefix}[{index}]"))
    return found


def assert_no_secrets_in_payload(payload: Any) -> None:
    """Raise ``ValueError`` if a serialized credential shape appears in the payload.

    Applied before writing ``raw_*_json`` columns (M2+) and available to tests
    for the "no secrets at rest" assertions (TEST_PLAN SEC-02).
    """
    serialized = _serialize(payload)
    if _SK_RE.search(serialized) or _BEARER_RE.search(serialized):
        raise ValueError("payload contains a credential-shaped string (sk-/Bearer)")


def _serialize(payload: Any) -> str:
    import json

    try:
        return json.dumps(payload, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(payload)
