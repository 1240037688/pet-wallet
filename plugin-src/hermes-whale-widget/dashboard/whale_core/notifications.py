"""Notifications — persistent dedup store + WS push / 3s-poll fallback source.

STUB (M0). Implemented in M7 (bubble queue data source) and M8 (reminder
writes). Dedup semantics: DATA_MODEL §2.10; rank: budget 1 > low-balance 2 >
turn cost 3 > waiting 4.
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M7/M8)
