"""Single-instance balance poller thread (M4).

Discipline (AGENTS.md §8/§9, ARCHITECTURE_DECISION §5):

* exactly one daemon thread per process, started lazily by the API runtime and
  stopped on ``reset_runtime`` (plugin reload / tests);
* interval from ``config.balance_poll_seconds`` re-read every cycle;
* **no credential → parked**: the loop keeps waking to re-check credentials
  but performs no network I/O, so track② is safely inert until the user
  configures one (PRV-00 precondition);
* every cycle is wrapped — a poller crash must never take the serve process
  down; failures are already data (balance_ledger error states);
* tests disable it via ``WHALE_WIDGET_DISABLE_POLLER=1`` (conftest) and drive
  ``refresh_balance`` synchronously instead.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from . import balance_ledger, config
from .logging_setup import get_logger

log = get_logger("poller")

_DISABLE_ENVS = ("PET_WALLET_DISABLE_POLLER", "WHALE_WIDGET_DISABLE_POLLER")
_WAKE_SLICE_S = 1.0  # stop responsiveness bound
_PARKED_INTERVAL_S = 60.0  # credential re-check period while parked

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()


def ensure_started(rt: Any) -> None:
    """Start the poller once (no-op when disabled by env or ledger corrupt)."""
    global _thread
    with _lock:
        if any(os.environ.get(k) == "1" for k in _DISABLE_ENVS):
            return
        if _thread is not None and _thread.is_alive():
            return
        if rt.conn is None:
            return
        _stop.clear()
        _thread = threading.Thread(target=_run, args=(rt,), name="whale-balance-poller", daemon=True)
        _thread.start()
        log.info("balance poller started")


def stop() -> None:
    """Signal the poller to exit; called on runtime reset (reload/tests)."""
    global _thread
    with _lock:
        _stop.set()
        _thread = None


def _run(rt: Any) -> None:
    while not _stop.is_set():
        try:
            interval = float(config.load_config().get("balance_poll_seconds", 60) or 60)
            interval = max(5.0, min(interval, 3600.0))
            conn = rt.conn
            if conn is None:
                break  # runtime reset / corrupt ledger → poller exits
            state = balance_ledger.refresh_balance(conn)
            # parked loop when not configured: cheaper fixed cadence, no I/O
            if state.get("refresh_skipped") == "not_configured":
                _sleep(min(_PARKED_INTERVAL_S, interval))
            else:
                _sleep(interval)
        except Exception as exc:  # noqa: BLE001 - poller must never crash serve
            log.error("balance poller cycle failed: %s", type(exc).__name__)
            _sleep(_PARKED_INTERVAL_S)


def _sleep(total: float) -> None:
    """Interruptible sleep (stop() takes effect within a second)."""
    waited = 0.0
    while waited < total and not _stop.is_set():
        _stop.wait(min(_WAKE_SLICE_S, total - waited))
        waited += _WAKE_SLICE_S
