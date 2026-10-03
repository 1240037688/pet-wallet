"""SEC-01: credential redaction — filter unit tests + end-to-end log file check."""

from __future__ import annotations

import logging

from whale_core.logging_setup import (
    BACKUP_COUNT,
    MAX_BYTES,
    SensitiveFilter,
    get_logger,
    redact,
    setup_logging,
)

FAKE_KEY = "sk-test-fake-1234567890abcdef"  # sanctioned fake (TEST_PLAN §2.1)


def make_record(msg: str, *args) -> logging.LogRecord:
    return logging.LogRecord(
        name="whale-widget.test", level=logging.INFO, pathname=__file__,
        lineno=1, msg=msg, args=args or None, exc_info=None,
    )


def test_redact_sk_key():
    out = redact(f"provider key {FAKE_KEY} rejected")
    assert FAKE_KEY not in out
    assert "sk-" + "***REDACTED***" in out


def test_redact_bearer_header():
    # contract is the SAFETY property (no secret survives, redaction marker
    # present) — the exact cosmetic form is not load-bearing
    out = redact("send Authorization: Bearer abc123def456ghi789 now")
    assert "abc123def456ghi789" not in out
    assert "***REDACTED***" in out
    assert "now" in out  # trailing prose survives


def test_redact_basic_auth_header():
    out = redact("Authorization: Basic dXNlcjpwYXNz")
    assert "dXNlcjpwYXNz" not in out
    assert "Basic" not in out  # scheme+value consumed as one secret


def test_redact_key_value_pairs():
    for line in (
        'config {"api_key": "abcd1234efgh"}',
        "token=zzzz9999yyyy",
        "Authorization: Basic dXNlcjpwYXNz",
        "refresh_token: aaaabbbbcccc",
    ):
        out = redact(line)
        assert "abcd1234efgh" not in out
        assert "zzzz9999yyyy" not in out
        assert "dXNlcjpwYXNz" not in out
        assert "aaaabbbbcccc" not in out
        assert "***REDACTED***" in out


def test_redact_keeps_fingerprints_and_plain_text():
    fingerprint = "a1b2c3d4e5f60718293a4b5c"  # sha256[:24] — sanctioned in logs
    text = f"fingerprint {fingerprint} balance ok, nothing else to see"
    assert redact(text) == text


def test_sensitive_filter_scrubs_record():
    filt = SensitiveFilter()
    record = make_record("request failed with key %s", FAKE_KEY)
    assert filt.filter(record) is True
    assert FAKE_KEY not in record.getMessage()
    assert record.args == ()  # args consumed after scrubbing


def test_setup_logging_writes_redacted_file(tmp_path):
    logger = setup_logging(tmp_path, also_stderr=False)
    try:
        logger = get_logger("test")
        logger.warning(f"balance fetch failed; key was {FAKE_KEY}")
        for handler in logging.getLogger("whale-widget").handlers:
            handler.flush()
        log_file = tmp_path / "logs" / "whale-widget.log"
        assert log_file.exists()
        content = log_file.read_text("utf-8")
        assert FAKE_KEY not in content
        assert "balance fetch failed" in content  # non-sensitive text survives
    finally:
        for handler in logging.getLogger("whale-widget").handlers[:]:
            logging.getLogger("whale-widget").removeHandler(handler)


def test_setup_logging_is_idempotent(tmp_path):
    setup_logging(tmp_path, also_stderr=False)
    setup_logging(tmp_path, also_stderr=False)  # re-invoke must not duplicate handlers
    root = logging.getLogger("whale-widget")
    file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1


def test_rotation_parameters_match_design(tmp_path):
    from logging.handlers import RotatingFileHandler

    setup_logging(tmp_path, also_stderr=False)
    root = logging.getLogger("whale-widget")
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == MAX_BYTES == 1_000_000  # 5 × 1MB, ARCH §6
    assert rotating[0].backupCount == BACKUP_COUNT == 5
    assert any(isinstance(f, SensitiveFilter) for f in rotating[0].filters)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
