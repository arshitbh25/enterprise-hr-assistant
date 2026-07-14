"""GET /api/v1/sessions.

Backs the P7 session sidebar (SDD Section 5.3): lists the current
user's sessions so the frontend can render one without needing to know
session IDs up front the way GET /history (Section 10.5) requires.
"""

from fastapi import APIRouter, Query

from app.api.deps import CurrentTenantIdDep, CurrentUserIdDep, SessionRepositoryDep
from app.api.schemas.sessions import SessionListResponse, SessionSummary

router = APIRouter()


@router.get("/sessions")
async def list_sessions(
    tenant_id: CurrentTenantIdDep,
    user_id: CurrentUserIdDep,
    session_repo: SessionRepositoryDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> SessionListResponse:
    items, total = session_repo.list_for_user(
        tenant_id, user_id, page=page, page_size=page_size
    )
    return SessionListResponse(
        items=[SessionSummary.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )
