"""Shared FastAPI dependency providers (SDD Section 5.3: API edge layer).

Centralizes request-scoped construction of repositories and identity
extraction so Module 8's route files don't each redeclare the same
Depends() wiring.
"""

import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.database.repositories.documents import DocumentRepository
from app.database.repositories.message_citations import MessageCitationRepository
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository
from app.database.repositories.tenants import TenantRepository
from app.database.repositories.users import UserRepository
from app.database.session import get_db_session
from app.services.llm_service import GeminiLLMService, LLMService


def get_current_settings(request: Request) -> Settings:
    """The exact Settings instance create_app() was built with (app.state),
    never the process-wide get_settings() cache - which can diverge from it
    (e.g. multiple app instances with different settings in the same
    process, as happens routinely in tests)."""
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_current_settings)]
DbSessionDep = Annotated[Session, Depends(get_db_session)]


def get_document_repository(db: DbSessionDep) -> DocumentRepository:
    return DocumentRepository(db)


def get_session_repository(db: DbSessionDep) -> SessionRepository:
    return SessionRepository(db)


def get_message_repository(db: DbSessionDep) -> MessageRepository:
    return MessageRepository(db)


def get_message_citation_repository(db: DbSessionDep) -> MessageCitationRepository:
    return MessageCitationRepository(db)


def get_tenant_repository(db: DbSessionDep) -> TenantRepository:
    return TenantRepository(db)


def get_user_repository(db: DbSessionDep) -> UserRepository:
    return UserRepository(db)


def get_llm_service(settings: SettingsDep) -> LLMService:
    return GeminiLLMService(settings)


def get_current_tenant_id(request: Request) -> uuid.UUID:
    """Identity attached by AuthStubMiddleware - never read from headers directly."""
    return uuid.UUID(str(request.state.tenant_id))


def get_current_user_id(request: Request) -> uuid.UUID:
    return uuid.UUID(str(request.state.user_id))


DocumentRepositoryDep = Annotated[DocumentRepository, Depends(get_document_repository)]
SessionRepositoryDep = Annotated[SessionRepository, Depends(get_session_repository)]
MessageRepositoryDep = Annotated[MessageRepository, Depends(get_message_repository)]
MessageCitationRepositoryDep = Annotated[
    MessageCitationRepository, Depends(get_message_citation_repository)
]
TenantRepositoryDep = Annotated[TenantRepository, Depends(get_tenant_repository)]
UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]
CurrentTenantIdDep = Annotated[uuid.UUID, Depends(get_current_tenant_id)]
CurrentUserIdDep = Annotated[uuid.UUID, Depends(get_current_user_id)]
LLMServiceDep = Annotated[LLMService, Depends(get_llm_service)]
