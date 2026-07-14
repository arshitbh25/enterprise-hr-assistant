"""Schemas for GET/DELETE /api/v1/documents (SDD Section 10.3, 10.4)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.core.constants import DocumentStatus


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    display_name: str
    size_bytes: int
    page_count: int | None
    chunk_count: int
    status: DocumentStatus
    failure_reason: str | None
    uploaded_by: uuid.UUID
    created_at: datetime
    ready_at: datetime | None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummary]
    total: int
    page: int
    page_size: int


class DocumentDeleteResponse(BaseModel):
    document_id: uuid.UUID
    chunks_removed: int
