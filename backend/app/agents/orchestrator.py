"""Orchestrator (SDD Section 6.2, ADR-003).

Deterministic sequential pipeline coordinator - no autonomous loops, no
LLM-driven control flow. Runs each agent in a fixed order, checking
after every stage whether the pipeline should stop early
(`context.short_circuit_reason` set by Context Ranking on an empty
result, Query Understanding on off-topic/greeting scope, or Response
Validation on a failed groundedness/leak/format check - SDD 6.4's "fail
closed on truthfulness"). Agents that only need to degrade gracefully
(Memory read failure, Query Understanding rewrite failure - "fail soft
on convenience") catch their own exceptions internally and never set
`short_circuit_reason`; the pipeline simply continues with whatever
fallback state that agent left in place.

Retries stay exactly where they already live: inside LLMService's own
backoff + circuit breaker (Phase 5). This module adds no second retry
layer - a genuine agent exception (e.g. LLMAgent surfacing a quota/
timeout/unavailable error) propagates straight out of `run_pipeline`
unchanged, to be mapped to its existing HTTP status by the global
DomainError handler exactly as it was in Phase 5's direct `chat.py` call.

`run_pipeline()`'s control-flow logic is tested against simple stub
agents (test_agents_orchestrator.py) so it's verified independently of
any specific agent's behavior. `build_pipeline()`/`build_memory_write_agent()`
below (Module 7) are the concrete, dependency-injected wiring: every
agent built by every prior module, assembled in the exact SDD 6.2
sequence. `MemoryWriteAgent` is deliberately excluded from the
stoppable list `build_pipeline()` returns and built separately -
SDD 6.3.9/`app.agents.memory`'s own docstring: it must run
unconditionally after the pipeline, even on a short-circuited turn.
"""

from app.agents.base import Agent, QueryContext
from app.agents.citation import CitationAgent
from app.agents.context_ranking import ContextRankingAgent
from app.agents.llm import LLMAgent
from app.agents.memory import MemoryReadAgent, MemoryWriteAgent
from app.agents.prompt_construction import PromptConstructionAgent
from app.agents.query_understanding import QueryUnderstandingAgent
from app.agents.response_validator import ResponseValidationAgent
from app.agents.retriever import RetrieverAgent
from app.agents.user_query import UserQueryAgent
from app.core.config import Settings
from app.database.repositories.documents import DocumentRepository
from app.database.repositories.message_citations import MessageCitationRepository
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository
from app.services.llm_service import LLMService


def run_pipeline(agents: list[Agent], context: QueryContext) -> QueryContext:
    for agent in agents:
        context = agent.run(context)
        if context.short_circuit_reason is not None:
            break
    return context


def build_pipeline(
    *,
    session_repo: SessionRepository,
    message_repo: MessageRepository,
    document_repo: DocumentRepository,
    llm_service: LLMService,
    settings: Settings,
) -> list[Agent]:
    """The stoppable main pipeline (SDD 6.2), in sequence. Call
    `run_pipeline(build_pipeline(...), context)`, then always run
    `build_memory_write_agent(...)` afterward - see module docstring."""
    return [
        UserQueryAgent(session_repo=session_repo, settings=settings),
        MemoryReadAgent(session_repo=session_repo, message_repo=message_repo, settings=settings),
        QueryUnderstandingAgent(llm_service=llm_service),
        RetrieverAgent(document_repo=document_repo, settings=settings),
        ContextRankingAgent(settings=settings),
        PromptConstructionAgent(settings=settings),
        LLMAgent(llm_service=llm_service),
        ResponseValidationAgent(settings=settings),
        CitationAgent(settings=settings),
    ]


def build_memory_write_agent(
    *,
    session_repo: SessionRepository,
    message_repo: MessageRepository,
    citation_repo: MessageCitationRepository,
    llm_service: LLMService,
    settings: Settings,
) -> MemoryWriteAgent:
    return MemoryWriteAgent(
        session_repo=session_repo,
        message_repo=message_repo,
        citation_repo=citation_repo,
        llm_service=llm_service,
        settings=settings,
    )
