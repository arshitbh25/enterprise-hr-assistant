"""Unit tests for MessageCitationRepository."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import MessageRole
from app.database.models import MessageCitation
from app.database.repositories.message_citations import MessageCitationRepository
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository
from app.rag.citations import Citation


def _message(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID):
    session = SessionRepository(db).create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    return MessageRepository(db).create(session=session, role=MessageRole.ASSISTANT, content="ans")


def _citation(**overrides) -> Citation:
    defaults = dict(
        chunk_id=uuid.uuid4(),
        document_name="Leave_Policy.pdf",
        page_start=12,
        page_end=12,
        section_title="Casual Leave",
        snippet="Employees receive twelve days of casual leave.",
    )
    defaults.update(overrides)
    return Citation(**defaults)


def test_bulk_create_persists_citations_in_rank_order(db: Session, seeded):
    tenant_id, user_id = seeded
    message = _message(db, tenant_id, user_id)
    citations = [
        _citation(document_name="A.pdf"),
        _citation(document_name="B.pdf"),
    ]

    rows = MessageCitationRepository(db).bulk_create(message.id, citations)

    assert [row.document_name for row in rows] == ["A.pdf", "B.pdf"]
    assert [row.rank for row in rows] == [0, 1]
    assert all(row.message_id == message.id for row in rows)

    stored = db.scalars(
        select(MessageCitation).where(MessageCitation.message_id == message.id)
    ).all()
    assert len(stored) == 2


def test_bulk_create_with_empty_list_returns_empty_list(db: Session, seeded):
    tenant_id, user_id = seeded
    message = _message(db, tenant_id, user_id)

    assert MessageCitationRepository(db).bulk_create(message.id, []) == []
