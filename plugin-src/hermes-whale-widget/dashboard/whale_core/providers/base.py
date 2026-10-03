"""HTTP client base for provider calls.

STUB (M0 — implemented in M4). Design requirement locked now (TEST_PLAN §2.1):
the client factory MUST accept an injectable ``transport`` so tests use
``httpx.MockTransport`` and never touch a real paid API.
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M4)
