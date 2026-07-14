"""Document repository (SDD Section 8.3: documents)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import DocumentStatus
from app.database.models import Document


class DocumentRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        tenant_id: uuid.UUID,
        uploaded_by: uuid.UUID,
        file_name: str,
        display_name: str,
        storage_path: str,
        content_hash: str,
        size_bytes: int,
        status: DocumentStatus = DocumentStatus.UPLOADED,
    ) -> Document:
        document = Document(
            tenant_id=tenant_id,
            uploaded_by=uploaded_by,
            file_name=file_name,
            display_name=display_name,
            storage_path=storage_path,
            content_hash=content_hash,
            size_bytes=size_bytes,
            status=status,
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document

    def get(self, tenant_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
        stmt = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        return self.db.scalars(stmt).first()

    def get_by_content_hash(self, tenant_id: uuid.UUID, content_hash: str) -> Document | None:
        stmt = select(Document).where(
            Document.tenant_id == tenant_id, Document.content_hash == content_hash
        )
        return self.db.scalars(stmt).first()

    def list(
        self,
        tenant_id: uuid.UUID,
        *,
        status: DocumentStatus | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Document], int]:
        base_stmt = select(Document).where(Document.tenant_id == tenant_id)
        if status is not None:
            base_stmt = base_stmt.where(Document.status == status)

        total = self.db.scalar(select(func.count()).select_from(base_stmt.subquery())) or 0

        items_stmt = (
            base_stmt.order_by(Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = list(self.db.scalars(items_stmt).all())
        return items, total

    def delete(self, document: Document) -> int:
        """Delete a document (cascades to its chunks). Returns its chunk_count."""
        chunk_count = document.chunk_count
        self.db.delete(document)
        self.db.commit()
        return chunk_count
