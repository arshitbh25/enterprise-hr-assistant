"""Shared fixtures for API contract tests: a real app, real migrations, real
temp SQLite file per test - no mocking of the DB layer.
"""

from collections.abc import Callable, Iterator
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
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def make_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """Factory: a real migrated temp SQLite DB per call, with optional field
    overrides (e.g. upload_max_file_mb=0 for a size-limit test).

    env.py reads DATABASE_URL via the global get_settings() cache, so both
    the env var and cache_clear() are required here - see Module 7's
    test_app_factory.py for why Config.sqlalchemy.url alone isn't enough.
    """
    counter = {"n": 0}

    def _make(**overrides: object) -> Settings:
        counter["n"] += 1
        db_path = tmp_path / f"api_test_{counter['n']}.db"
        database_url = f"sqlite:///{db_path.as_posix()}"
        storage_dir = str(tmp_path / f"storage_{counter['n']}")
        chroma_dir = str(tmp_path / f"chroma_{counter['n']}")

        monkeypatch.setenv("DATABASE_URL", database_url)
        get_settings.cache_clear()

        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(cfg, "head")

        kwargs: dict[str, object] = {
            "database_url": database_url,
            "storage_dir": storage_dir,
            "chroma_dir": chroma_dir,
        }
        kwargs.update(overrides)
        return Settings(_env_file=None, **kwargs)

    return _make


@pytest.fixture()
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings()


@pytest.fixture()
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture()
def make_client(make_settings: Callable[..., Settings]) -> Callable[..., TestClient]:
    """Factory for tests needing non-default settings, e.g.:
    `with make_client(upload_max_file_mb=0) as client: ...`
    """

    def _make(**overrides: object) -> TestClient:
        return TestClient(create_app(make_settings(**overrides)))

    return _make
