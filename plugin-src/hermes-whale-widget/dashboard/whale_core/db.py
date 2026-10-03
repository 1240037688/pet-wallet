"""SQLite connection management for whale.db (M0).

Discipline (DATA_MODEL §7 / ARCHITECTURE_DECISION DR-9):

* pragmas on every connection: ``journal_mode=WAL`` + ``synchronous=FULL``
  (crash safety over write amplification), ``foreign_keys=ON``,
  ``busy_timeout=5000`` (Windows indexer short-lock backoff lives at callers).
* corruption is fail-closed: a failed integrity probe on open dumps the file
  aside as ``whale.db.corrupt-<ts>`` and raises :class:`LedgerCorruptError` —
  never silently overwrite, never half-write.
* single writer = the Python half (serve process); test/preview code may open
  extra read connections via :func:`connect_ro`.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from .logging_setup import get_logger

log = get_logger("db")

BUSY_TIMEOUT_MS = 5000


class LedgerCorruptError(RuntimeError):
    """Raised when whale.db fails its integrity probe; writes are refused."""


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) whale.db with the standard pragma set.

    ``check_same_thread=False``: the router's sync handlers run on FastAPI's
    threadpool threads, so the shared connection IS used from multiple threads
    (sqlite3 serializes access internally at the C level; concurrent write
    discipline is WAL + busy_timeout + single-writer design, DATA_MODEL §7.1).
    """
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=BUSY_TIMEOUT_MS / 1000.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.DatabaseError as exc:
        # e.g. "file is not a database" on pragma execution — fail closed.
        conn.close()
        _dump_and_raise(path, f"open-time pragma failed: {exc}")
    _fail_closed_on_corruption(conn, path)
    return conn


def connect_ro(db_path: str | Path) -> sqlite3.Connection:
    """Read-only connection (tests, previews); same failure discipline."""
    path = Path(db_path)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_MS / 1000.0)
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    return conn


def _fail_closed_on_corruption(conn: sqlite3.Connection, path: Path) -> None:
    try:
        row = conn.execute("PRAGMA quick_check(1)").fetchone()
    except sqlite3.DatabaseError as exc:
        conn.close()
        _dump_and_raise(path, f"integrity probe raised: {exc}")
        return
    result = row[0] if row is not None else None
    if result != "ok":
        conn.close()
        _dump_and_raise(path, f"integrity probe reported: {result!r}")


def _dump_and_raise(path: Path, reason: str) -> None:
    dumped = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        if path.exists():
            path.replace(dumped)
    except OSError as exc:  # could not move it aside — still refuse to write
        log.error("corrupt db %s could not be quarantined: %s", path, exc)
    log.error("whale.db refused (fail-closed): %s; quarantined at %s", reason, dumped)
    raise LedgerCorruptError(f"{reason} (file quarantined: {dumped.name})") from None
