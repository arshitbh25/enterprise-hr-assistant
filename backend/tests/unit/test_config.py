"""Unit tests for app.core.config.Settings."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings


def test_defaults_load_without_env_file():
    settings = Settings(_env_file=None)
    assert settings.app_env == "local"
    assert settings.log_level == "INFO"
    assert settings.cors_origins_list == ["http://localhost:5173"]
    assert settings.upload_max_file_mb == 25
    assert settings.upload_max_files == 10
    assert settings.rate_limit_per_minute == 10
    assert settings.session_ttl_hours == 24
    assert settings.session_title_max_chars == 60


def test_cors_origins_parsed_from_comma_separated_string(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    settings = Settings(_env_file=None)
    assert settings.cors_origins_list == ["http://a.test", "http://b.test"]


def test_cors_origins_accepts_single_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://only.test")
    settings = Settings(_env_file=None)
    assert settings.cors_origins_list == ["http://only.test"]


def test_invalid_int_field_raises_validation_error(monkeypatch):
    monkeypatch.setenv("UPLOAD_MAX_FILE_MB", "not-a-number")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_invalid_app_env_raises_validation_error(monkeypatch):
    monkeypatch.setenv("APP_ENV", "not-a-real-env")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_env_var_overrides_default(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "42")
    settings = Settings(_env_file=None)
    assert settings.rate_limit_per_minute == 42


def test_get_settings_is_cached():
    get_settings.cache_clear()
    first = get_settings()
    second = get_settings()
    assert first is second
    get_settings.cache_clear()
