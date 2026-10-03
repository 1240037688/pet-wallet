"""Data directory resolution and config.json read/write (M0).

Persistence layout (ARCHITECTURE_DECISION §6, per-profile scope):

    <HERMES_HOME>/whale-widget/
    ├── whale.db / -wal / -shm
    ├── config.json          ← this module (no secrets, ever)
    ├── credentials.json     ← fallback only, never written by M0
    ├── approval-state.json  ← M8
    └── logs/whale-widget.log

``HERMES_HOME`` resolution order (test injection friendly — TEST_PLAN §2.3):
    1. explicit ``home=`` argument (tests)
    2. ``hermes_constants.get_hermes_home()`` — honours the per-request profile
       scope the web server binds around plugin routes (production path)
    3. ``HERMES_HOME`` environment variable (tests / manual runs)
    4. ``~/.hermes`` (last resort)

config.json holds NO credentials (AGENTS.md §7). Unknown keys on write are
rejected (whitelist); on read they are ignored. Writes are atomic
(tmp file + os.replace) and always deep-merge over DEFAULTS on read.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from copy import deepcopy
from pathlib import Path
from typing import Any

_PLUGIN_DIR_NAME = "whale-widget"

CONFIG_FILENAME = "config.json"

# Write whitelist: only these top-level sections may be persisted via PUT /config.
# Keys never allowed anywhere in the payload (defense in depth; REST responses
# and logs are additionally scanned by whale_core.security).
FORBIDDEN_KEY_SUBSTRINGS = ("secret", "token", "password", "api_key", "apikey", "credential")

DEFAULTS: dict[str, Any] = {
    # Polling (single-instance rule lives in the Python half, ARCH §5)
    "balance_poll_seconds": 60,
    "usage_summary_poll_seconds": 30,
    # Reminders (M8 consumes; M0 only stores)
    "reminders": {
        "balance_low_enabled": True,
        "budget_enabled": True,
        "turn_cost_enabled": True,
    },
    "thresholds": {
        # None = unset (null ≠ 0 semantics, DATA_MODEL §8.3)
        "balance_low": None,
        "daily_budget": None,
        # M8 per-turn notification floor (decimal currency amount; None = no floor)
        "turn_cost_min": None,
    },
    # Bubbles (M7 consumes; M0 only stores)
    "bubbles": {
        "enabled": True,
        "turn_cost_ttl_ms": 5000,
    },
    # Sound (M9; engine exists but no clips ship by default → silent until
    # the user configures assets; enabled=false keeps the Phase-1 default quiet)
    "sound": {
        "enabled": False,
        "muted": False,
        "volume_global": 100,
    },
}

_lock = threading.Lock()


def hermes_home(home: str | Path | None = None) -> Path:
    """Resolve the Hermes home directory (see module docstring for the order)."""
    if home is not None:
        return Path(home)
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env)
    try:  # production: honours the per-request profile scope (ContextVar)
        from hermes_constants import get_hermes_home  # type: ignore

        return Path(get_hermes_home())
    except Exception:  # noqa: BLE001 - not running inside hermes serve
        return Path.home() / ".hermes"


def data_dir(home: str | Path | None = None) -> Path:
    """``<HERMES_HOME>/whale-widget/`` — created on demand, never inside the code tree."""
    path = hermes_home(home) / _PLUGIN_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path(home: str | Path | None = None) -> Path:
    return data_dir(home) / CONFIG_FILENAME


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursive merge; override wins on scalars, dicts merge per-key."""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_config(home: str | Path | None = None) -> dict[str, Any]:
    """Read config.json and deep-merge over DEFAULTS. Corrupt/missing file → defaults.

    A corrupt config is renamed aside (``config.json.corrupt-<ts>``) so the next
    write starts clean — fail-open for display config, mirroring the ledger's
    "never silently overwrite" discipline.
    """
    path = config_path(home)
    if not path.exists():
        return deepcopy(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _quarantine(path)
        return deepcopy(DEFAULTS)
    if not isinstance(raw, dict):
        _quarantine(path)
        return deepcopy(DEFAULTS)
    return _deep_merge(DEFAULTS, raw)


def _quarantine(path: Path) -> None:
    import time

    try:
        path.replace(path.with_name(f"{CONFIG_FILENAME}.corrupt-{int(time.time())}"))
    except OSError:
        pass


def validate_config_update(payload: Any) -> dict[str, Any]:
    """Whitelist + no-secret validation for incoming config writes.

    Returns the validated section dict; raises ``ValueError`` with a
    user-safe message on any violation (message never echoes the payload).
    """
    if not isinstance(payload, dict):
        raise ValueError("config update must be a JSON object")
    unknown = sorted(k for k in payload if k not in DEFAULTS)
    if unknown:
        # key names only, never values
        raise ValueError(f"unknown config section(s): {', '.join(unknown)}")
    if _contains_forbidden_key(payload):
        raise ValueError("config update contains a forbidden (credential-like) field name")
    return payload


def _contains_forbidden_key(obj: Any) -> bool:
    if isinstance(obj, dict):
        for key, value in obj.items():
            k = str(key).lower()
            if any(pat in k for pat in FORBIDDEN_KEY_SUBSTRINGS):
                return True
            if _contains_forbidden_key(value):
                return True
    elif isinstance(obj, list):
        return any(_contains_forbidden_key(item) for item in obj)
    return False


def save_config(update: dict[str, Any], home: str | Path | None = None) -> dict[str, Any]:
    """Merge ``update`` into the stored config and atomically rewrite the file.

    Returns the merged config that is now persisted.
    """
    with _lock:
        current = load_config(home)
        merged = _deep_merge(current, validate_config_update(update))
        path = config_path(home)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(path, merged)
        return merged


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp_name, path)  # atomic on same volume (Windows: os.replace)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def reset_defaults(home: str | Path | None = None) -> dict[str, Any]:
    """Restore factory defaults (used by tests and the future settings UI)."""
    with _lock:
        path = config_path(home)
        _atomic_write_json(path, DEFAULTS)
        return deepcopy(DEFAULTS)
