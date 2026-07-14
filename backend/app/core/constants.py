"""Shared enums used across the domain (SDD Section 9: core/constants.py).

Kept separate from app/database/models.py so non-DB code (future agents,
services) can reference e.g. DocumentStatus.READY without importing
SQLAlchemy.
"""

import enum


class TenantStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserRole(str, enum.Enum):
    EMPLOYEE = "employee"
    HR_ADMIN = "hr_admin"
    SYSTEM_ADMIN = "system_admin"


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "high"
    LOW = "low"
    NOT_FOUND = "not_found"


class FeedbackRating(str, enum.Enum):
    UP = "up"
    DOWN = "down"


class QueryOutcome(str, enum.Enum):
    ANSWERED = "answered"
    NOT_FOUND = "not_found"
    REFUSED = "refused"
    ERROR = "error"


# FR-Q03: the standard refusal message - a correct refusal is a successful
# response (200, not_found: true), never a guess. Used verbatim by the v1
# chat stub (Module 8), which has no retrieval/LLM yet and is honestly
# reporting that no grounded answer is currently possible.
STANDARD_NOT_FOUND_MESSAGE = (
    "I could not find this in the uploaded HR policy documents. Please contact HR."
)

# FR-Q08: every answer includes a one-line disclaimer that HR is the final authority.
HR_DISCLAIMER = "HR remains the final authority on all policy matters."

# SDD Section 6.3.5/7.2 Stage 9: the exact token the LLM must emit verbatim
# when the sources don't support an answer. Distinct from
# STANDARD_NOT_FOUND_MESSAGE (the user-facing text) - this is what the
# model itself is instructed to output; app/rag/citations.py checks for
# an exact match before ever showing the user-facing message.
NOT_FOUND_TOKEN = "NOT_FOUND"

# SDD Appendix A / ADR-002. Recorded on every chunk (Section 8.3) from Phase 3
# onward even though no vector is computed until Phase 4 - the column exists
# precisely so a future model swap is a re-index job, not a schema change.
EMBEDDING_MODEL_NAME = "bge-small-en-v1.5"

# SDD Section 6.3.2, FR-Q07: scope short-circuits from the Query
# Understanding Agent, before any retrieval/generation is spent.
GREETING_RESPONSE_MESSAGE = (
    "Hello! I'm the HR policy assistant. Ask me anything about company HR policy."
)
SCOPE_REFUSAL_MESSAGE = (
    "I can only help with questions about HR policy. Please contact HR for anything else."
)
