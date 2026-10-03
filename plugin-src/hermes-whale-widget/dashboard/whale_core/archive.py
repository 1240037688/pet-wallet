"""Archive — retention policy executor (DATA_MODEL §5).

STUB (M0). Implemented in M2: daily tick + opportunistic prune after turn
settlement; UsageEvent/TurnCost/BalanceSnapshot/DailySummary move into the
``*_archive`` tables (never deleted); Notification/SessionWatermark deleted
outright at expiry.
"""

from __future__ import annotations  # noqa: F401  (stub module — implemented in M2)
