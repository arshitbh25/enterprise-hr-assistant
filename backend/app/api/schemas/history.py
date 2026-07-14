"""Schemas for GET/DELETE /api/v1/history (SDD Section 10.5, 10.6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.api.schemas.chat import Citation
from app.core.constants import ConfidenceLevel, MessageRole


class HistoryTurn(BaseModel):
    role: MessageRole
    content: str
    citations: list[Citation]
    confidence: ConfidenceLevel | None
    created_at: datetime


class HistoryResponse(BaseModel):
    session_id: uuid.UUID
    title: str | None
    turns: list[HistoryTurn]


class HistoryDeleteResponse(BaseModel):
    sessions_cleared: int
    messages_deleted: int
