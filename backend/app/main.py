"""FastAPI application factory (SDD Section 5.3, 9).

Kept as a factory - not a module-level `app = FastAPI()` - so tests can
build isolated instances against isolated settings/databases. The
lifespan boots logging, initializes the DB engine, and seeds the default
tenant/user; it deliberately does NOT create tables itself (SDD 3.7: "DB
migrations run as a release step"), so a schema-missing DB fails fast at
boot with an actionable message rather than a cryptic SQL error on the
first request.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import OperationalError

from app.agents.memory import init_summarize_template
from app.agents.query_understanding import init_rewrite_template
from app.api.spa import mount_spa
from app.api.v1 import chat, documents, health, history, sessions, upload
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.database.seed import seed_defaults
from app.database.session import get_session_factory, init_engine
from app.embeddings.registry import init_embedder
from app.middleware.auth import AuthStubMiddleware
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.request_id import RequestIDMiddleware
from app.rag.prompt_builder import init_prompt_templates

logger = get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings)
        init_engine(settings)
        init_embedder(settings)
        init_prompt_templates()
        init_rewrite_template()
        init_summarize_template()

        db = get_session_factory()()
        try:
            seed_defaults(db, settings)
        except OperationalError as exc:
            raise RuntimeError(
                "Database schema is not initialized. Run `alembic upgrade head` "
                "(from backend/) before starting the app."
            ) from exc
        finally:
            db.close()

        logger.info("app_started", app_env=settings.app_env, app_version=settings.app_version)
        yield
        logger.info("app_stopped")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    app.state.settings = settings

    register_exception_handlers(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # add_middleware() inserts at the front of the stack, so the LAST one
    # added ends up OUTERMOST (runs first). We want execution order
    # request_id -> auth -> rate_limit -> routing, so add in reverse.
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(AuthStubMiddleware, settings=settings)
    app.add_middleware(RequestIDMiddleware, settings=settings)

    app.include_router(health.router, prefix="/api/v1", tags=["health"])
    app.include_router(upload.router, prefix="/api/v1", tags=["documents"])
    app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
    app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
    app.include_router(history.router, prefix="/api/v1", tags=["history"])
    app.include_router(sessions.router, prefix="/api/v1", tags=["sessions"])

    # Railway single-service deployment only (ADR-011): local dev/tests
    # never set frontend_dist_dir, so this is a no-op everywhere else.
    if settings.frontend_dist_dir:
        mount_spa(app, Path(settings.frontend_dist_dir))

    return app
