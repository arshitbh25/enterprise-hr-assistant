"""SQLAlchemy engine/session wiring (SDD Section 8.1: SQLite v1 -> Postgres later).

Synchronous SQLAlchemy is a deliberate simplification for v1: async
SQLite (aiosqlite) + async Alembic migrations add real complexity for
zero benefit on a local file. The repository layer isolates this choice
(ADR-005/009) so a future async Postgres engine only touches this
module, not callers.
"""

from collections.abc import Generator
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


def _ensure_sqlite_directory_exists(database_url: str) -> None:
    """SQLite needs its parent directory to exist before connecting."""
    if not database_url.startswith("sqlite:///"):
        return
    db_path = database_url.removeprefix("sqlite:///")
    if db_path in (":memory:", ""):
        return
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def create_db_engine(settings: Settings) -> Engine:
    _ensure_sqlite_directory_exists(settings.database_url)
    connect_args = (
        {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    )
    return create_engine(settings.database_url, connect_args=connect_args)


_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def init_engine(settings: Settings | None = None) -> Engine:
    """Idempotently (re)initialize the process-wide engine/sessionmaker.

    Called once from the app factory's lifespan (Module 7); tests build
    their own isolated engine directly via create_db_engine() instead of
    touching this process-wide singleton.
    """
    global _engine, _session_factory
    settings = settings or get_settings()
    _engine = create_db_engine(settings)
    _session_factory = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, expire_on_commit=False
    )
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    if _session_factory is None:
        init_engine()
    assert _session_factory is not None
    return _session_factory


def get_db_session() -> Generator[Session, None, None]:
    """FastAPI dependency: one Session per request, closed after."""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
