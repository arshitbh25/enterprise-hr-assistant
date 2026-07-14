"""Shared fixtures for repository/seed unit tests."""

import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.database.models import Base
from app.database.seed import seed_defaults


@pytest.fixture()
def db() -> Session:
    """Isolated in-memory SQLite DB, fresh per test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(_env_file=None)


@pytest.fixture()
def seeded(db: Session, test_settings: Settings) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed the default tenant/user; returns (tenant_id, user_id)."""
    seed_defaults(db, test_settings)
    return uuid.UUID(test_settings.default_tenant_id), uuid.UUID(test_settings.default_user_id)
