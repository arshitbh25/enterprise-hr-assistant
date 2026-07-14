"""GET /api/v1/health (SDD Section 10.7).

vector_store and embedding_model are real checks as of Phase 4; llm is
honestly reported "not_configured" (Phase 5 wires that in) rather than
faked as "up", which is why overall status is "degraded" rather than
"healthy" until then.
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbSessionDep, SettingsDep
from app.api.schemas.health import HealthChecks, HealthResponse
from app.core.logging import get_logger
from app.embeddings.registry import get_embedder
from app.services.vector_store import ChromaVectorStore

router = APIRouter()
logger = get_logger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep, db: DbSessionDep) -> HealthResponse | JSONResponse:
    database_status = "up"
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any DB failure means "down", detail doesn't matter here
        logger.error("health_check_database_failed")
        database_status = "down"

    vector_store_status = "up" if ChromaVectorStore(settings).heartbeat() else "down"

    try:
        get_embedder()
        embedding_model_status = "up"
    except Exception:  # noqa: BLE001 - any failure to reach the embedder means "down"
        logger.error("health_check_embedding_model_failed")
        embedding_model_status = "down"

    checks = HealthChecks(
        api="up",
        database=database_status,
        vector_store=vector_store_status,
        embedding_model=embedding_model_status,
        llm="not_configured",
    )

    check_values = checks.model_dump().values()
    if "down" in check_values:
        overall = "unhealthy"
    elif "not_configured" in check_values:
        overall = "degraded"
    else:
        overall = "healthy"

    response = HealthResponse(status=overall, checks=checks, version=settings.app_version)

    if overall == "unhealthy":
        return JSONResponse(status_code=503, content=response.model_dump())
    return response
