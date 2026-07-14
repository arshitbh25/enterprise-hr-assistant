"""Message citation repository (SDD Section 8.3: message_citations)."""

import uuid

from sqlalchemy.orm import Session

from app.database.models import MessageCitation
from app.rag.citations import Citation


class MessageCitationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def bulk_create(
        self, message_id: uuid.UUID, citations: list[Citation]
    ) -> list[MessageCitation]:
        rows = [
            MessageCitation(
                message_id=message_id,
                chunk_id=citation.chunk_id,
                document_name=citation.document_name,
                page_start=citation.page_start,
                page_end=citation.page_end,
                snippet=citation.snippet,
                rank=rank,
            )
            for rank, citation in enumerate(citations)
        ]
        self.db.add_all(rows)
        self.db.commit()
        for row in rows:
            self.db.refresh(row)
        return rows
