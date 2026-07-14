"""Session repository (SDD Section 8.3: sessions).

get() requires both tenant_id and user_id to match (Section 11.5: chat
history is user-scoped, one employee can never read another's questions).
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session as ORMSession

from app.database.models import Message
from app.database.models import Session as SessionModel


class SessionRepository:
    def __init__(self, db: ORMSession) -> None:
        self.db = db

    def create(self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, ttl_hours: int) -> SessionModel:
        now = datetime.now(UTC)
        session = SessionModel(
            tenant_id=tenant_id,
            user_id=user_id,
            created_at=now,
            last_activity_at=now,
            expires_at=now + timedelta(hours=ttl_hours),
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(
        self, tenant_id: uuid.UUID, user_id: uuid.UUID, session_id: uuid.UUID
    ) -> SessionModel | None:
        stmt = select(SessionModel).where(
            SessionModel.id == session_id,
            SessionModel.tenant_id == tenant_id,
            SessionModel.user_id == user_id,
            SessionModel.is_deleted.is_(False),
        )
        return self.db.scalars(stmt).first()

    def list_for_user(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SessionModel], int]:
        base_stmt = select(SessionModel).where(
            SessionModel.tenant_id == tenant_id,
            SessionModel.user_id == user_id,
            SessionModel.is_deleted.is_(False),
        )

        total = self.db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0

        items_stmt = (
            base_stmt.order_by(SessionModel.last_activity_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.scalars(items_stmt).all())
        return items, total

    def update_title(self, session: SessionModel, title: str) -> SessionModel:
        """Auto-title a session from its first user question (SDD 8.3)."""
        session.title = title
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update_summary(self, session: SessionModel, summary: str) -> SessionModel:
        """Persist a refreshed rolling summary (SDD 6.3.9: summary
        refresh every M turns via a cheap Gemini call)."""
        session.summary = summary
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def delete(self, session: SessionModel) -> int:
        """Hard-delete a session; cascades to its messages. Returns messages deleted."""
        message_count = (
            self.db.scalar(
                select(func.count()).select_from(Message).where(Message.session_id == session.id)
            )
            or 0
        )
        self.db.delete(session)
        self.db.commit()
        return message_count

    def delete_all_for_user(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> tuple[int, int]:
        stmt = select(SessionModel).where(
            SessionModel.tenant_id == tenant_id,
            SessionModel.user_id == user_id,
            SessionModel.is_deleted.is_(False),
        )
        sessions = list(self.db.scalars(stmt).all())
        sessions_cleared = 0
        messages_deleted = 0
        for session in sessions:
            messages_deleted += self.delete(session)
            sessions_cleared += 1
        return sessions_cleared, messages_deleted
