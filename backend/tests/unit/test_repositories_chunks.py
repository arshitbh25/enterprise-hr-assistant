"""Unit tests for ChunkRepository."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models import Chunk
from app.database.repositories.chunks import ChunkRepository
from app.database.repositories.documents import DocumentRepository
from app.rag.metadata import ChunkDraft


def _document(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID):
    return DocumentRepository(db).create(
        tenant_id=tenant_id,
        uploaded_by=user_id,
        file_name="leave_policy.pdf",
        display_name="Leave Policy",
        storage_path="uploads/tenant/leave_policy.pdf",
        content_hash="a" * 64,
        size_bytes=1024,
    )


def _draft(document_id: uuid.UUID, tenant_id: uuid.UUID, **overrides) -> ChunkDraft:
    defaults = dict(
        document_id=document_id,
        tenant_id=tenant_id,
        chunk_index=0,
        text="Employees receive twelve days of annual leave.",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        token_count=8,
        embedding_model="bge-small-en-v1.5",
        content_hash="b" * 64,
    )
    defaults.update(overrides)
    return ChunkDraft(**defaults)


def test_bulk_create_persists_all_chunks(db: Session, seeded):
    tenant_id, user_id = seeded
    document = _document(db, tenant_id, user_id)
    drafts = [
        _draft(document.id, tenant_id, chunk_index=0, content_hash="a" * 64),
        _draft(document.id, tenant_id, chunk_index=1, content_hash="b" * 64),
    ]

    chunks = ChunkRepository(db).bulk_create(drafts)

    assert len(chunks) == 2
    assert all(c.id is not None for c in chunks)
    stored = db.scalars(select(Chunk).where(Chunk.document_id == document.id)).all()
    assert len(stored) == 2


def test_delete_by_document_removes_only_that_documents_chunks(db: Session, seeded):
    tenant_id, user_id = seeded
    document_a = _document(db, tenant_id, user_id)
    document_b = DocumentRepository(db).create(
        tenant_id=tenant_id,
        uploaded_by=user_id,
        file_name="other.pdf",
        display_name="Other",
        storage_path="uploads/tenant/other.pdf",
        content_hash="c" * 64,
        size_bytes=512,
    )
    repo = ChunkRepository(db)
    repo.bulk_create([_draft(document_a.id, tenant_id, content_hash="d" * 64)])
    repo.bulk_create([_draft(document_b.id, tenant_id, content_hash="e" * 64)])

    removed = repo.delete_by_document(document_a.id)

    assert removed == 1
    remaining = db.scalars(select(Chunk)).all()
    assert len(remaining) == 1
    assert remaining[0].document_id == document_b.id


def test_delete_by_document_with_no_chunks_returns_zero(db: Session, seeded):
    tenant_id, user_id = seeded
    document = _document(db, tenant_id, user_id)

    assert ChunkRepository(db).delete_by_document(document.id) == 0
