"""Unit tests for app.main.create_app (the FastAPI app factory + lifespan)."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.main import create_app

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    """_migrated_settings() populates the process-wide get_settings() cache
    via env.py during the migration; guarantee it never leaks into other
    tests regardless of this test's outcome."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _migrated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> Settings:
    """Run real migrations against a fresh temp DB, return Settings pointing at it.

    env.py deliberately reads the DB URL from the global get_settings()
    singleton (so `alembic upgrade head` always targets the exact DB the
    app would use) rather than trusting Config.sqlalchemy.url directly -
    so the env var + cache_clear() here is required, not optional.
    """
    db_path = tmp_path / "app_factory_test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")

    return Settings(_env_file=None, database_url=database_url, **overrides)


def test_create_app_seeds_defaults_on_startup(tmp_path, monkeypatch):
    settings = _migrated_settings(tmp_path, monkeypatch)
    app = create_app(settings)

    with TestClient(app):
        pass  # lifespan startup/shutdown runs here

    db_path = settings.database_url.removeprefix("sqlite:///")
    conn = sqlite3.connect(db_path)
    try:
        tenant_count = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()

    assert tenant_count == 1
    assert user_count == 1


def test_create_app_raises_clear_error_when_schema_missing(tmp_path):
    db_path = tmp_path / "unmigrated.db"
    settings = Settings(_env_file=None, database_url=f"sqlite:///{db_path.as_posix()}")
    app = create_app(settings)

    with pytest.raises(Exception, match="alembic upgrade head"):
        with TestClient(app):
            pass


def test_unmatched_route_returns_error_envelope_with_request_id(tmp_path, monkeypatch):
    settings = _migrated_settings(tmp_path, monkeypatch)
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get("/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["request_id"]
    assert response.headers["X-Request-ID"] == body["request_id"]


def test_rate_limited_response_still_carries_a_request_id(tmp_path, monkeypatch):
    """Proves execution order request_id -> auth -> rate_limit: even a 429
    short-circuited by RateLimitMiddleware carries a correlated request_id,
    which only happens if RequestIDMiddleware wraps it (Module 5 note)."""
    settings = _migrated_settings(tmp_path, monkeypatch, rate_limit_per_minute=1)
    app = create_app(settings)

    with TestClient(app) as client:
        first = client.get("/does-not-exist")
        second = client.get("/does-not-exist")

    assert first.status_code == 404
    assert second.status_code == 429
    body = second.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert body["request_id"]
