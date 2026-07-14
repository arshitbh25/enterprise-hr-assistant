"""Schemas for POST /api/v1/chat (SDD Section 10.2)."""

import uuid

from pydantic import BaseModel

from app.core.constants import ConfidenceLevel


class ChatRequest(BaseModel):
    session_id: uuid.UUID | None = None
    # Deliberately unconstrained here: length/emptiness validation happens
    # in the route so a bad question maps to the specific INVALID_QUESTION
    # error code (SDD 10.2), not FastAPI's generic VALIDATION_FAILED.
    question: str


class Citation(BaseModel):
    document_name: str
    pages: list[int]
    section: str | None = None
    # FR-Q04 / SDD 6.3.8: the supporting snippet the Citation Agent already
    # computes (app/rag/citations.py Citation.snippet) - added for the
    # frontend's expandable citation card (Phase 7), which had no snippet
    # to render without this: the route was building this schema from the
    # same source object but leaving the field on the floor.
    snippet: str


class ChatResponse(BaseModel):
    session_id: uuid.UUID
    message_id: uuid.UUID
    answer: str
    confidence: ConfidenceLevel
    citations: list[Citation]
    not_found: bool
    latency_ms: int
    request_id: str | None = None
