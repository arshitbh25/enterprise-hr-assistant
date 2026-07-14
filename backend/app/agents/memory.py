"""Conversation Memory Agent (SDD Section 6.3.9, FR-S05).

Two agent classes sharing the read/write logic in this one module,
rather than one class run twice with internal mode-switching - the SDD
gives Memory a read path (early in the pipeline) and a write path
(late, after the answer is finalized), which are genuinely two
different points in the sequence:

- `MemoryReadAgent`: last `settings.memory_window_turns` user+assistant
  pairs plus the session's rolling summary.
- `MemoryWriteAgent`: persists the completed turn (question, answer,
  citations, confidence, latency, token usage), auto-titles the session
  from the first question (SDD 8.3) the first time it writes to it, and
  periodically refreshes the rolling summary via a small Gemini call.

`MemoryWriteAgent` runs *unconditionally* after the main pipeline,
regardless of whether it stopped early via `short_circuit_reason` -
even a NOT_FOUND/off-topic/greeting turn gets persisted with its
refusal answer, matching Phase 5's existing behavior. It is therefore
never included in the stoppable `run_pipeline()` agent list; the
wiring code (Module 7) calls it separately, always, as the last step.

Failure cases: read DB failure -> proceed memory-less (fail soft, SDD's
own wording: "a stateless answer beats no answer"); summary refresh
failure -> keep the previous summary (fail soft), logged - the turn's
own persistence has already succeeded by that point regardless.
"""

import string
from pathlib import Path

from app.agents.base import MemoryTurn, QueryContext, agent_stage, format_memory_turns
from app.core.config import Settings
from app.core.constants import MessageRole
from app.core.logging import get_logger
from app.database.models import Message
from app.database.repositories.message_citations import MessageCitationRepository
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository
from app.services.llm_service import LLMService

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_SUMMARIZE_TEMPLATE_NAME = "summarize_v1.txt"

_summarize_template: string.Template | None = None


def init_summarize_template() -> None:
    """Load and cache the summarize template. Called once from the app
    lifespan; raises (fails boot) if the file is missing or unreadable."""
    global _summarize_template
    path = _PROMPTS_DIR / _SUMMARIZE_TEMPLATE_NAME
    _summarize_template = string.Template(path.read_text(encoding="utf-8"))


def get_summarize_template() -> string.Template:
    if _summarize_template is None:
        init_summarize_template()
    assert _summarize_template is not None
    return _summarize_template


def _build_title(question: str, max_chars: int) -> str:
    """Truncate the first question into a session title (SDD 8.3). Cuts on
    a char boundary rather than a word boundary - simple and predictable,
    and titles are display-only so mid-word truncation is an acceptable
    trade for not adding a word-wrap dependency."""
    text = question.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def _pair_into_turns(messages: list[Message]) -> list[MemoryTurn]:
    """messages must already be ordered oldest-first. Pairs consecutive
    (user, assistant) messages; a malformed/unpaired message is skipped
    defensively rather than crashing the read path."""
    turns: list[MemoryTurn] = []
    index = 0
    while index + 1 < len(messages):
        user_message, assistant_message = messages[index], messages[index + 1]
        is_valid_pair = (
            user_message.role == MessageRole.USER
            and assistant_message.role == MessageRole.ASSISTANT
        )
        if is_valid_pair:
            turns.append(
                MemoryTurn(question=user_message.content, answer=assistant_message.content)
            )
            index += 2
        else:
            index += 1
    return turns


class MemoryReadAgent:
    name = "memory_read"

    def __init__(
        self,
        *,
        session_repo: SessionRepository,
        message_repo: MessageRepository,
        settings: Settings,
    ) -> None:
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            try:
                session = self._session_repo.get(
                    context.tenant_id, context.user_id, context.session_id
                )
                if session is None:
                    raise ValueError("session not found during memory read")
                messages = self._message_repo.list_for_session(session.id)
                turns = _pair_into_turns(messages)
                context.memory_turns = turns[-self._settings.memory_window_turns :]
                context.memory_summary = session.summary
            except Exception as exc:  # noqa: BLE001 - fail soft: proceed memory-less
                context.stage_statuses[self.name] = "degraded"
                context.memory_turns = []
                context.memory_summary = None
                logger.warning(
                    "memory_read_failed", request_id=context.request_id, exc_info=exc
                )
        return context


class MemoryWriteAgent:
    name = "memory_write"

    def __init__(
        self,
        *,
        session_repo: SessionRepository,
        message_repo: MessageRepository,
        citation_repo: MessageCitationRepository,
        llm_service: LLMService,
        settings: Settings,
    ) -> None:
        self._session_repo = session_repo
        self._message_repo = message_repo
        self._citation_repo = citation_repo
        self._llm_service = llm_service
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            # If the session genuinely can't be found here, losing the
            # whole turn's persistence is a real problem worth surfacing
            # (not a convenience to fail soft on) - UserQueryAgent just
            # created/verified this exact session earlier in the request.
            session = self._session_repo.get(
                context.tenant_id, context.user_id, context.session_id
            )
            if session is None:
                raise ValueError("session not found during memory write")

            if session.title is None:
                title = _build_title(context.raw_question, self._settings.session_title_max_chars)
                self._session_repo.update_title(session, title)

            self._message_repo.create(
                session=session,
                role=MessageRole.USER,
                content=context.raw_question,
                standalone_query=context.standalone_query,
            )
            usage = context.llm_usage or {}
            assistant_message = self._message_repo.create(
                session=session,
                role=MessageRole.ASSISTANT,
                content=context.final_answer or "",
                confidence=context.confidence,
                latency_ms=sum(context.stage_timings.values()),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
            if context.citations:
                self._citation_repo.bulk_create(assistant_message.id, context.citations)
            context.assistant_message_id = assistant_message.id

            self._maybe_refresh_summary(context, session)
        return context

    def _maybe_refresh_summary(self, context: QueryContext, session) -> None:
        interval = self._settings.memory_summary_refresh_interval_turns
        if interval <= 0:
            return

        messages = self._message_repo.list_for_session(session.id)
        turn_count = len(messages) // 2
        if turn_count == 0 or turn_count % interval != 0:
            return

        try:
            turns = _pair_into_turns(messages)[-self._settings.memory_window_turns :]
            prompt = get_summarize_template().substitute(
                previous_summary=session.summary or "(none)",
                conversation=format_memory_turns(turns),
            )
            summary = self._llm_service.generate(prompt).text.strip()
            if summary:
                self._session_repo.update_summary(session, summary)
        except Exception as exc:  # noqa: BLE001 - fail soft: keep the previous summary
            logger.warning(
                "summary_refresh_failed", request_id=context.request_id, exc_info=exc
            )
