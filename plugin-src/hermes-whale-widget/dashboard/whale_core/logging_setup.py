"""Logging setup: rotating file log + sensitive-data redaction filter (M0).

Log target: ``<data_dir>/logs/whale-widget.log`` — RotatingFileHandler,
5 × 1 MB (ARCHITECTURE_DECISION §6).

Redaction (AGENTS.md §7 / DATA_MODEL §8.4 / [TP] SEC-01): every record is
scrubbed for
  * ``sk-<...>`` API-key shapes (fake test keys ``sk-test-`` included —
    a leaked test key in a log is still a bad log),
  * ``Bearer <token>`` authorization values,
  * ``authorization`` / ``api[-_]key`` / ``token`` key-value pairs,
  * long hex/base64-ish bearer-ish runs attached to ``key``/``token`` words.

Fingerprints (sha256 prefixes) are deliberately NOT redacted — they are the
sanctioned way credentials appear in logs (ARCH §8.1).
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIRNAME = "logs"
LOG_FILENAME = "pet-wallet.log"
MAX_BYTES = 1_000_000  # 1 MB
BACKUP_COUNT = 5

_LOGGER_NAME = "pet-wallet"

# --- redaction patterns -----------------------------------------------------
# sk- shapes: sk- followed by >=8 secret-ish chars. `sk-test-...` fixtures are
# redacted too (log hygiene is unconditional).
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")
# Authorization-header value with an explicit scheme (Basic/NTLS/…) — two
# whitespace-separated tokens at most, so trailing prose survives.
_AUTH_HEADER_RE = re.compile(
    r"\b(authorization|proxy-authorization)(\"?)\s*([:=])\s*(\"?)"
    r"\S+(?:\s\S+)?",
    re.IGNORECASE,
)
# Authorization header value / explicit Bearer scheme (standalone form).
_BEARER_RE = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=\-]{6,}", re.IGNORECASE)
# key-value pairs: "authorization: xxx", "api_key=xxx", {"token": "xxx"}
_KV_RE = re.compile(
    r"\b(authorization|api[-_]?key|access[-_]?token|refresh[-_]?token|secret|token)"
    r"(\"?)\s*([:=])\s*(\"?)"
    r"[A-Za-z0-9._~+/=\-]{6,}",
    re.IGNORECASE,
)

REDACTED = "***REDACTED***"


def redact(text: str) -> str:
    """Return ``text`` with credential-shaped substrings replaced."""
    if not text:
        return text
    text = _AUTH_HEADER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{REDACTED}", text)
    text = _BEARER_RE.sub("Bearer " + REDACTED, text)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{m.group(4)}{REDACTED}", text)
    text = _SK_KEY_RE.sub("sk-" + REDACTED, text)
    return text


class SensitiveFilter(logging.Filter):
    """Logging filter that redacts credential shapes from every record.

    Applies to record.getMessage() output (message + args rendered), then
    stores the scrubbed string as the record's final message.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - logging API
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never break logging on bad args
            return True
        scrubbed = redact(message)
        if scrubbed != message:
            record.msg = scrubbed
            record.args = ()
        return True


def setup_logging(
    data_dir: str | Path,
    *,
    level: int = logging.INFO,
    also_stderr: bool = True,
) -> logging.Logger:
    """Idempotently configure the whale-widget logger (rotating file + optional stderr).

    Returns the package logger. Re-invocation replaces handlers instead of
    duplicating them (safe under plugin reload).
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    for existing in list(logger.handlers):
        logger.removeHandler(existing)
        try:
            existing.close()
        except Exception:  # noqa: BLE001
            pass

    log_dir = Path(data_dir) / LOG_DIRNAME
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s [%(name)s] %(message)s")
    )
    file_handler.addFilter(SensitiveFilter())
    logger.addHandler(file_handler)

    if also_stderr:
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter("%(levelname)-7s [%(name)s] %(message)s"))
        stream.addFilter(SensitiveFilter())
        logger.addHandler(stream)

    return logger


def get_logger(category: str) -> logging.Logger:
    """Child logger with a module/category tag, e.g. ``whale-widget.db``."""
    return logging.getLogger(f"{_LOGGER_NAME}.{category}")
