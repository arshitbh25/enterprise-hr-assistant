"""User Query Agent (SDD Section 6.3.1).

Responsibility: entry gate. Sanitizes input (strip + length cap),
resolves the session (creating one if none was requested), and screens
for prompt-injection patterns.

Input: `context.raw_question` (as typed by the user) and
`context.session_id` (the caller's *requested* session id - `None`
means "create a new one"). Output: `context.raw_question` normalized
(stripped), `context.session_id` overwritten with the resolved/created
session's actual id, `context.suspicious`.

Communication: API -> this agent -> (next) Memory Agent.

Failure cases: empty/oversized question -> `InvalidQuestionError` (422);
a requested `session_id` that doesn't resolve -> `SessionNotFoundError`
(404). Both relocated unchanged from Phase 5's `chat.py` - same codes,
same behavior, now raised from here instead. Injection patterns detected
-> `context.suspicious = True` and logged, but the question is still
processed (SDD 6.3.1: "question still processed under hardened prompt
rules" - the hardening is structural, in the Phase 5 prompt template's
own anti-injection rules).
"""

import re

from app.agents.base import QueryContext, agent_stage
from app.core.config import Settings
from app.core.exceptions import InvalidQuestionError, SessionNotFoundError
from app.core.logging import get_logger
from app.database.repositories.sessions import SessionRepository

logger = get_logger(__name__)

_MAX_QUESTION_LENGTH = 2000

_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore (all|any|previous|the above)?\s*instructions",
        r"disregard (all|any|the above)?\s*(instructions|rules)",
        r"reveal (your|the) (system prompt|instructions|rules)",
        r"you are now",
        r"act as (if|though)",
        r"system prompt",
    )
]


class UserQueryAgent:
    name = "user_query"

    def __init__(self, *, session_repo: SessionRepository, settings: Settings) -> None:
        self._session_repo = session_repo
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            question = context.raw_question.strip()
            if not question or len(question) > _MAX_QUESTION_LENGTH:
                raise InvalidQuestionError()
            context.raw_question = question

            if any(pattern.search(question) for pattern in _INJECTION_PATTERNS):
                context.suspicious = True
                logger.warning(
                    "suspicious_question_flagged", request_id=context.request_id
                )

            if context.session_id is None:
                session = self._session_repo.create(
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    ttl_hours=self._settings.session_ttl_hours,
                )
            else:
                session = self._session_repo.get(
                    context.tenant_id, context.user_id, context.session_id
                )
                if session is None:
                    raise SessionNotFoundError()
            context.session_id = session.id

        return context
