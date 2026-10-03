"""Ingest endpoints — POST /ingest/turn, POST /ingest/wait-event.

STUB (M0). M1 defines the contract (payload validation, ``{status:'accepted'}``),
M2 replaces this with the real idempotent ledger write
(dedup_key / watermark / turn_seq / INSERT OR IGNORE — DATA_MODEL §3).
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M1/M2)
