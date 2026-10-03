"""HTTP client base and error taxonomy for provider calls (M4).

Design requirement locked in M0 (TEST_PLAN §2.1): the client factory accepts
an injectable ``transport`` so tests use ``httpx.MockTransport`` and never
touch a real paid API.

Error taxonomy: every failure mode the PRV test domain exercises maps to one
exception kind, and :attr:`ProviderError.kind` is the stable string the state
machine persists — never the raw exception text, which could echo URLs or
response bodies; kinds cannot.
"""

from __future__ import annotations

from typing import Any

import httpx

DEFAULT_TIMEOUT_S = 10.0


class ProviderError(Exception):
    """Base for all provider failures; ``kind`` is the persisted discriminator."""

    kind = "provider_error"
    http_status: int | None = None

    def __init__(self, message: str | None = None, *, http_status: int | None = None) -> None:
        super().__init__(message or self.kind)
        if http_status is not None:
            self.http_status = http_status


class ProviderNotConfigured(ProviderError):
    """No credential resolvable for the provider — track② stays disabled."""

    kind = "not_configured"


class ProviderAuthError(ProviderError):
    """401/403 — credential rejected; never treat as zero balance."""

    kind = "auth"


class ProviderRateLimited(ProviderError):
    """429 — back off; state must keep the last known balance."""

    kind = "rate_limited"


class ProviderServerError(ProviderError):
    """5xx — upstream trouble; state must keep the last known balance."""

    kind = "server"


class ProviderBadResponse(ProviderError):
    """Body was not usable JSON or the configured field path was missing."""

    kind = "bad_response"


class ProviderNetworkError(ProviderError):
    """Connection-level failure (DNS, refused, TLS)."""

    kind = "network"


class ProviderTimeout(ProviderError):
    kind = "timeout"


def raise_for_status(resp: httpx.Response) -> None:
    """Map an HTTP status onto the provider error taxonomy (PRV domain)."""
    if resp.status_code < 400:
        return
    if resp.status_code in (401, 403):
        raise ProviderAuthError("credential rejected", http_status=resp.status_code)
    if resp.status_code == 429:
        raise ProviderRateLimited("rate limited", http_status=resp.status_code)
    if resp.status_code >= 500:
        raise ProviderServerError("server error", http_status=resp.status_code)
    raise ProviderBadResponse("unexpected http status", http_status=resp.status_code)


def open_client(transport: Any = None) -> httpx.Client:
    """Build the outbound client (timeout-bounded; transport injectable for tests)."""
    return httpx.Client(transport=transport, timeout=DEFAULT_TIMEOUT_S)
