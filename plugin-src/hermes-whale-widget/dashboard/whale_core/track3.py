"""Track③ — read-only cross-check against Hermes ``state.db``.

DEFERRED-BY-DESIGN (V2): the track① (usage events) + track② (balance
observation) pair already closes the accounting loop; the read-only state.db
cross-check is an ENHANCEMENT, recorded in DATA_MODEL §4.1 / DR-11 and
REMAINING_WORK.md P3-2. Planned shape when picked up: ``mode=ro`` URI open,
``schema_version`` gate, PRAGMA table_info column degradation, fail-open —
never 500s the UI (DATA_MODEL §4.4).
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M2)
