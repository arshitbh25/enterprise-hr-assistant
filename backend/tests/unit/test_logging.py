"""Unit tests for app.core.logging."""

from app.core.config import Settings
from app.core.logging import (
    bind_request_id,
    clear_request_context,
    configure_logging,
    get_logger,
    get_request_id,
    scrub_pii,
)


def test_request_id_bind_get_clear_roundtrip():
    clear_request_context()
    assert get_request_id() is None
    bind_request_id("req-123")
    assert get_request_id() == "req-123"
    clear_request_context()
    assert get_request_id() is None


def test_scrub_pii_redacts_email():
    text = "Contact me at jane.doe@example.com for details."
    scrubbed = scrub_pii(text)
    assert "jane.doe@example.com" not in scrubbed
    assert "[REDACTED_EMAIL]" in scrubbed


def test_scrub_pii_redacts_phone_number():
    text = "Call me at +1 415-555-0132 tomorrow."
    scrubbed = scrub_pii(text)
    assert "415-555-0132" not in scrubbed
    assert "[REDACTED_PHONE]" in scrubbed


def test_scrub_pii_redacts_long_numeric_id():
    text = "My employee ID is 480215639."
    scrubbed = scrub_pii(text)
    assert "480215639" not in scrubbed
    assert "[REDACTED_ID]" in scrubbed


def test_scrub_pii_leaves_normal_text_untouched():
    text = "How many casual leaves do I get per year?"
    assert scrub_pii(text) == text


def test_configure_logging_local_env_does_not_raise():
    configure_logging(Settings(_env_file=None, app_env="local"))
    logger = get_logger("test")
    logger.info("smoke_test_event", detail="ok")


def test_configure_logging_production_env_does_not_raise():
    configure_logging(Settings(_env_file=None, app_env="production"))
    logger = get_logger("test")
    logger.info("smoke_test_event", detail="ok")
    configure_logging(Settings(_env_file=None, app_env="local"))
