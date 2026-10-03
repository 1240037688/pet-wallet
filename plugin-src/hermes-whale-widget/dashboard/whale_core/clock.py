"""Injectable time source (TEST_PLAN §2.3 — M0 convention).

Every ``whale_core`` module that needs "now" goes through :func:`now_ms`, so
tests can pin the clock for day-key, minute-bucket, FRESH_TTL and
monotonic-sample determinism (M2/M4 consumers).
"""

from __future__ import annotations

import time
from typing import Callable

_clock: Callable[[], float] = time.time


def now_ms() -> int:
    """Current epoch milliseconds, per the (injectable) clock."""
    return int(_clock() * 1000)


def set_clock(fn: Callable[[], float]) -> None:
    """Test hook: replace the underlying time function (e.g. a fake)."""
    global _clock
    _clock = fn


def reset_clock() -> None:
    """Restore the real wall clock."""
    global _clock
    _clock = time.time
