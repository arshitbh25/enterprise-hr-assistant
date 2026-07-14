"""POST /api/v1/chat (SDD Section 10.2, Section 6.2).

Module 7: replaces Phase 5/6's direct retrieve/rank/prompt/generate/cite
calls with the full agent pipeline (Modules 3-6), run through the
orchestrator. The route's own job narrows to: build the initial
QueryContext from the request + resolved identity, run the stoppable
pipeline (`build_pipeline`), always run `MemoryWriteAgent` afterward -
even a short-circuited NOT_FOUND/off-topic/greeting turn is persisted,
matching Phase 5's own behavior (SDD 6.3.9) - then translate the final
QueryContext into the response schema.

Per-agent validation and exception mapping (InvalidQuestionError,
SessionNotFoundError, NoDocumentsIndexedError, the LLMService error
family) all now live inside the agents themselves (Modules 3-6) and
propagate unchanged through the existing global DomainError handler -
no mapping code needed here, same as before.
"""

import time

from fastapi import APIRouter

from app.agents.base import QueryContext
from app.agents.orchestrator import build_memory_write_agent, build_pipeline, run_pipeline
from app.api.deps import (
    CurrentTenantIdDep,
    CurrentUserIdDep,
    DocumentRepositoryDep,
    LLMServiceDep,
    MessageCitationRepositoryDep,
    MessageRepositoryDep,
    SessionRepositoryDep,
    SettingsDep,
)
from app.api.schemas.chat import ChatRequest, ChatResponse
from app.api.schemas.chat import Citation as CitationSchema
from app.core.constants import ConfidenceLevel
from app.core.logging import get_request_id

router = APIRouter()


@router.post("/chat")
async def chat(
    payload: ChatRequest,
    tenant_id: CurrentTenantIdDep,
    user_id: CurrentUserIdDep,
    settings: SettingsDep,
    session_repo: SessionRepositoryDep,
    message_repo: MessageRepositoryDep,
    document_repo: DocumentRepositoryDep,
    citation_repo: MessageCitationRepositoryDep,
    llm_service: LLMServiceDep,
) -> ChatResponse:
    started_at = time.perf_counter()

    context = QueryContext(
        request_id=get_request_id() or "",
        tenant_id=tenant_id,
        user_id=user_id,
        raw_question=payload.question,
        session_id=payload.session_id,
    )

    pipeline = build_pipeline(
        session_repo=session_repo,
        message_repo=message_repo,
        document_repo=document_repo,
        llm_service=llm_service,
        settings=settings,
    )
    context = run_pipeline(pipeline, context)

    memory_write_agent = build_memory_write_agent(
        session_repo=session_repo,
        message_repo=message_repo,
        citation_repo=citation_repo,
        llm_service=llm_service,
        settings=settings,
    )
    context = memory_write_agent.run(context)

    return ChatResponse(
        session_id=context.session_id,
        message_id=context.assistant_message_id,
        answer=context.final_answer or "",
        confidence=context.confidence or ConfidenceLevel.NOT_FOUND,
        citations=[
            CitationSchema(
                document_name=citation.document_name,
                pages=list(range(citation.page_start, citation.page_end + 1)),
                section=citation.section_title,
                snippet=citation.snippet,
            )
            for citation in context.citations
        ],
        not_found=context.not_found,
        latency_ms=round((time.perf_counter() - started_at) * 1000),
        request_id=context.request_id,
    )
