"""Unit tests for DocumentRepository."""

import uuid

from sqlalchemy.orm import Session

from app.core.constants import DocumentStatus
from app.database.repositories.documents import DocumentRepository


def _create_document(repo: DocumentRepository, tenant_id, user_id, **overrides):
    defaults = {
        "tenant_id": tenant_id,
        "uploaded_by": user_id,
        "file_name": "leave_policy.pdf",
        "display_name": "Leave Policy",
        "storage_path": "/data/uploads/leave_policy.pdf",
        "content_hash": "a" * 64,
        "size_bytes": 1024,
    }
    defaults.update(overrides)
    return repo.create(**defaults)


def test_create_and_get_document(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = DocumentRepository(db)
    document = _create_document(repo, tenant_id, user_id)

    fetched = repo.get(tenant_id, document.id)
    assert fetched is not None
    assert fetched.file_name == "leave_policy.pdf"
    assert fetched.status == DocumentStatus.UPLOADED
    assert fetched.chunk_count == 0


def test_get_is_scoped_to_tenant(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = DocumentRepository(db)
    document = _create_document(repo, tenant_id, user_id)

    assert repo.get(uuid.uuid4(), document.id) is None


def test_get_by_content_hash_detects_duplicate(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = DocumentRepository(db)
    document = _create_document(repo, tenant_id, user_id, content_hash="b" * 64)

    found = repo.get_by_content_hash(tenant_id, "b" * 64)
    assert found is not None
    assert found.id == document.id
    assert repo.get_by_content_hash(tenant_id, "c" * 64) is None


def test_list_paginates_and_filters_by_status(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = DocumentRepository(db)
    for i in range(3):
        _create_document(
            repo, tenant_id, user_id, content_hash=str(i) * 64, file_name=f"doc{i}.pdf"
        )

    items, total = repo.list(tenant_id, page=1, page_size=2)
    assert total == 3
    assert len(items) == 2

    items, total = repo.list(tenant_id, status=DocumentStatus.READY)
    assert total == 0
    assert items == []


def test_delete_removes_document(db: Session, seeded):
    tenant_id, user_id = seeded
    repo = DocumentRepository(db)
    document = _create_document(repo, tenant_id, user_id)

    chunks_removed = repo.delete(document)
    assert chunks_removed == 0
    assert repo.get(tenant_id, document.id) is None
