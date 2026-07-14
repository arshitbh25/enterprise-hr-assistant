"""Chunk repository (SDD Section 8.3: chunks)."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database.models import Chunk
from app.rag.metadata import ChunkDraft


class ChunkRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bulk_create(self, drafts: list[ChunkDraft]) -> list[Chunk]:
        chunks = [
            Chunk(
                document_id=draft.document_id,
                tenant_id=draft.tenant_id,
                chunk_index=draft.chunk_index,
                text=draft.text,
                page_start=draft.page_start,
                page_end=draft.page_end,
                section_title=draft.section_title,
                token_count=draft.token_count,
                embedding_model=draft.embedding_model,
                content_hash=draft.content_hash,
            )
            for draft in drafts
        ]
        self.db.add_all(chunks)
        self.db.commit()
        for chunk in chunks:
            self.db.refresh(chunk)
        return chunks

    def delete_by_document(self, document_id: uuid.UUID) -> int:
        count = (
            self.db.scalar(
                select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
            )
            or 0
        )
        self.db.execute(delete(Chunk).where(Chunk.document_id == document_id))
        self.db.commit()
        return count
