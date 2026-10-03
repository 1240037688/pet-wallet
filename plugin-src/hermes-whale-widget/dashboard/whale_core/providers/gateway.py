"""Credential gateway: secret resolution, fingerprints, outbound whitelist.

STUB (M0 — implemented in M4). Secrets exist ONLY in this half (DR-3): resolve
via Hermes secret_sources (fallback credentials.json), expose fingerprints
(sha256[:24]) and {credential_id, name, configured, source} to the outside.
Outbound rule: credentials may only go to template-pinned origins.
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M4)
