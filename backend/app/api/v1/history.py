"""GET/DELETE /api/v1/history (SDD Section 10.5, 10.6).

Cursor pagination ("before" param) from Section 10.5 is not implemented
in this stub - only `limit` (most-recent-N) - since no FR mandates full
cursor semantics and there is no real conversation volume yet to need it.
"""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import (
    CurrentTenantIdDep,
    CurrentUserIdDep,
    MessageRepositoryDep,
    SessionRepositoryDep,
)
from app.api.schemas.history import HistoryDeleteResponse, HistoryResponse, HistoryTurn
from app.core.exceptions import SessionNotFoundError, ValidationFailedError

router = APIRouter()


@router.get("/history")
async def get_history(
    tenant_id: CurrentTenantIdDep,
    user_id: CurrentUserIdDep,
    session_repo: SessionRepositoryDep,
    message_repo: MessageRepositoryDep,
    session_id: uuid.UUID = Query(...),
    limit: int | None = Query(default=None, ge=1),
) -> HistoryResponse:
    session = session_repo.get(tenant_id, user_id, session_id)
    if session is None:
        raise SessionNotFoundError()

    messages = message_repo.list_for_session(session.id)
    if limit is not None:
        messages = messages[-limit:]

    return HistoryResponse(
        session_id=session.id,
        title=session.title,
        turns=[
            HistoryTurn(
                role=message.role,
                content=message.content,
                citations=[],
                confidence=message.confidence,
                created_at=message.created_at,
            )
            for message in messages
        ],
    )


@router.delete("/history")
async def delete_history(
    tenant_id: CurrentTenantIdDep,
    user_id: CurrentUserIdDep,
    session_repo: SessionRepositoryDep,
    session_id: uuid.UUID | None = Query(default=None),
    all_sessions: bool = Query(default=False, alias="all"),
) -> HistoryDeleteResponse:
    if session_id is None and not all_sessions:
        raise ValidationFailedError(
            "Either session_id or all=true must be provided.", status_code=422
        )

    if all_sessions:
        sessions_cleared, messages_deleted = session_repo.delete_all_for_user(tenant_id, user_id)
    else:
        session = session_repo.get(tenant_id, user_id, session_id)
        if session is None:
            raise SessionNotFoundError()
        messages_deleted = session_repo.delete(session)
        sessions_cleared = 1

    return HistoryDeleteResponse(
        sessions_cleared=sessions_cleared, messages_deleted=messages_deleted
    )
