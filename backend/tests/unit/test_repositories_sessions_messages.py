"""Unit tests for SessionRepository and MessageRepository."""

import uuid
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.constants import MessageRole
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository


def test_create_and_get_session(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)
    session = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)

    fetched = repo.get(tenant_id, user_id, session.id)
    assert fetched is not None
    assert fetched.id == session.id
    assert fetched.expires_at > fetched.created_at


def test_get_denies_access_for_wrong_user(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)
    session = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)

    assert repo.get(tenant_id, uuid.uuid4(), session.id) is None


def test_update_title(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)
    session = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    assert session.title is None

    repo.update_title(session, "How many casual leaves do I get?")

    refreshed = repo.get(tenant_id, user_id, session.id)
    assert refreshed.title == "How many casual leaves do I get?"


def test_delete_session_cascades_messages(db: Session, seeded):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)

    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    message_repo.create(session=session, role=MessageRole.USER, content="How many casual leaves?")
    message_repo.create(session=session, role=MessageRole.ASSISTANT, content="Placeholder answer.")

    messages_deleted = session_repo.delete(session)
    assert messages_deleted == 2
    assert session_repo.get(tenant_id, user_id, session.id) is None


def test_delete_all_for_user(db: Session, seeded):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)

    for _ in range(2):
        session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
        message_repo.create(session=session, role=MessageRole.USER, content="Question")

    sessions_cleared, messages_deleted = session_repo.delete_all_for_user(tenant_id, user_id)
    assert sessions_cleared == 2
    assert messages_deleted == 2


def test_message_repository_list_for_session_ordered(db: Session, seeded):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)

    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    message_repo.create(session=session, role=MessageRole.USER, content="First")
    message_repo.create(session=session, role=MessageRole.ASSISTANT, content="Second")

    messages = message_repo.list_for_session(session.id)
    assert [m.content for m in messages] == ["First", "Second"]


def test_message_repository_bumps_session_last_activity(db: Session, seeded):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)

    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    original_activity = session.last_activity_at
    message_repo.create(session=session, role=MessageRole.USER, content="Hi")

    assert session.last_activity_at >= original_activity


def test_list_for_user_empty_by_default(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)

    items, total = repo.list_for_user(tenant_id, user_id)
    assert items == []
    assert total == 0


def test_list_for_user_orders_by_last_activity_desc(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)

    oldest = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    newest = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    newest.last_activity_at = oldest.last_activity_at + timedelta(minutes=5)
    db.add(newest)
    db.commit()

    items, total = repo.list_for_user(tenant_id, user_id)
    assert total == 2
    assert [s.id for s in items] == [newest.id, oldest.id]


def test_list_for_user_excludes_soft_deleted(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)

    active = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    deleted = repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    deleted.is_deleted = True
    db.add(deleted)
    db.commit()

    items, total = repo.list_for_user(tenant_id, user_id)
    assert total == 1
    assert items[0].id == active.id


def test_list_for_user_excludes_other_users_and_tenants(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)

    repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    repo.create(tenant_id=tenant_id, user_id=uuid.uuid4(), ttl_hours=24)
    repo.create(tenant_id=uuid.uuid4(), user_id=user_id, ttl_hours=24)

    items, total = repo.list_for_user(tenant_id, user_id)
    assert total == 1


def test_list_for_user_pagination(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = SessionRepository(db)

    for _ in range(3):
        repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)

    items, total = repo.list_for_user(tenant_id, user_id, page=1, page_size=2)
    assert total == 3
    assert len(items) == 2
