"""Schemas for GET /api/v1/sessions.

Added alongside Phase 7 (frontend) to back the session sidebar (SDD
Section 5.3, P7 exit criteria): the SDD's original design assumed
GET /history could double as a session list, but /history requires a
specific session_id (Section 10.5) - there was never an endpoint that
lists a user's sessions. This mirrors documents.py's list/pagination
shape (Section 10.3) rather than inventing a new one.
"""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SessionSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    last_activity_at: datetime


class SessionListResponse(BaseModel):
    items: list[SessionSummary]
    total: int
    page: int
    page_size: int
