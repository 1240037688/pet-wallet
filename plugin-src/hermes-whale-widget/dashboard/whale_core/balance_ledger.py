"""Track② balance ledger — snapshots, differencing, adjustments.

STUB (M0). Implemented in M4: monotonic snapshot ingestion, observed_spend /
credit differencing (top-up never cancels spend), daily materialisation,
revision-409 adjustment endpoint (DATA_MODEL §2.5-§2.7, §6 state machine).
Hard rule preview (M4): API failure ≠ 0; error/stale/unknown states never
produce amount writes.
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M4)
