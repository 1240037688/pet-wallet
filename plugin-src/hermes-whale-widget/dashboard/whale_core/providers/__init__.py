"""Provider gateway package — credential-aware outbound HTTP for balance APIs.

STUB (M0). base.py/gateway.py arrive in M4 (httpx client with injectable
transport, 15s timeout, one retry on network/5xx, in-flight dedup; secret
resolution + fingerprint + outbound origin whitelist + assertSafeApiUrl),
deepseek.py is the first vendor template (M4), registry.py the user-template
store (M11).
"""

from __future__ import annotations  # noqa: F401  (stub package — implemented in M4/M11)
