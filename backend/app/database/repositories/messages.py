"""Message repository (SDD Section 8.3: messages)."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as ORMSession

from app.core.constants import ConfidenceLevel, MessageRole
from app.database.models import Message
from app.database.models import Session as SessionModel


class MessageRepository:
    def __init__(self, db: ORMSession) -> None:
        self.db = db

    def create(
        self,
        *,
        session: SessionModel,
        role: MessageRole,
        content: str,
        standalone_query: str | None = None,
        confidence: ConfidenceLevel | None = None,
        latency_ms: int | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> Message:
        message = Message(
            session_id=session.id,
            role=role,
            content=content,
            standalone_query=standalone_query,
            confidence=confidence,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self.db.add(message)
        session.last_activity_at = datetime.now(UTC)
        self.db.add(session)
        self.db.commit()
        self.db.refresh(message)
        return message

    def list_for_session(self, session_id: uuid.UUID) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.asc())
        )
        return list(self.db.scalars(stmt).all())
