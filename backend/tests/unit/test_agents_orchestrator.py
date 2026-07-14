"""Unit tests for app/agents/orchestrator.py (SDD Section 6.2, 6.4, ADR-003).

Uses simple stub agents rather than the real Phase 5/6 agents (those
land in later modules) - this file tests the orchestrator's own
control-flow logic in isolation: agents run in order, a
short_circuit_reason set by any agent stops the pipeline before the
remaining agents run, a genuine exception propagates unchanged (no
second retry layer), and a fail-soft agent's self-reported degradation
never stops the pipeline.
"""

import uuid

import pytest

from app.agents.base import QueryContext, agent_stage
from app.agents.orchestrator import build_memory_write_agent, build_pipeline, run_pipeline
from app.core.constants import ConfidenceLevel, DocumentStatus, MessageRole
from app.core.exceptions import NoDocumentsIndexedError
from app.database.repositories.documents import DocumentRepository
from app.database.repositories.message_citations import MessageCitationRepository
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository
from app.rag.retriever import RetrievedChunk
from tests._fakes import FakeLLMService, _default_response


def _context() -> QueryContext:
    return QueryContext(
        request_id=str(uuid.uuid4()),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_question="How many casual leaves do I get?",
    )


class _RecordingAgent:
    def __init__(self, name: str, calls: list[str], *, short_circuit: bool = False):
        self.name = name
        self._calls = calls
        self._short_circuit = short_circuit

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            self._calls.append(self.name)
            if self._short_circuit:
                context.short_circuit_reason = f"{self.name}_stopped"
        return context


class _FailingAgent:
    def __init__(self, name: str):
        self.name = name

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            raise RuntimeError(f"{self.name} exploded")
        return context  # pragma: no cover - unreachable, keeps type checkers calm


class _DegradingAgent:
    """Simulates a fail-soft agent: catches its own failure internally,
    marks itself degraded, and never sets short_circuit_reason."""

    def __init__(self, name: str, calls: list[str]):
        self.name = name
        self._calls = calls

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            try:
                raise RuntimeError("memory backend unavailable")
            except RuntimeError:
                context.stage_statuses[self.name] = "degraded"
            self._calls.append(self.name)
        return context


def test_run_pipeline_runs_all_agents_in_order_when_nothing_short_circuits():
    calls: list[str] = []
    agents = [
        _RecordingAgent("first", calls),
        _RecordingAgent("second", calls),
        _RecordingAgent("third", calls),
    ]

    result = run_pipeline(agents, _context())

    assert calls == ["first", "second", "third"]
    assert result.stage_statuses == {"first": "ok", "second": "ok", "third": "ok"}


def test_run_pipeline_stops_after_a_short_circuit_fail_closed():
    calls: list[str] = []
    agents = [
        _RecordingAgent("first", calls),
        _RecordingAgent("second", calls, short_circuit=True),
        _RecordingAgent("third", calls),
    ]

    result = run_pipeline(agents, _context())

    assert calls == ["first", "second"]  # "third" never runs
    assert result.short_circuit_reason == "second_stopped"


def test_run_pipeline_propagates_a_genuine_agent_exception():
    agents = [_FailingAgent("boom")]

    with pytest.raises(RuntimeError, match="boom exploded"):
        run_pipeline(agents, _context())


def test_run_pipeline_continues_past_a_fail_soft_degraded_agent():
    calls: list[str] = []
    agents = [
        _DegradingAgent("memory_read", calls),
        _RecordingAgent("retriever", calls),
    ]

    result = run_pipeline(agents, _context())

    assert calls == ["memory_read", "retriever"]  # pipeline continued
    assert result.stage_statuses["memory_read"] == "degraded"
    assert result.stage_statuses["retriever"] == "ok"
    assert result.short_circuit_reason is None


# --- build_pipeline() / build_memory_write_agent() (Module 7 wiring) ---


def _built_pipeline(db, test_settings):
    return build_pipeline(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        document_repo=DocumentRepository(db),
        llm_service=FakeLLMService(),
        settings=test_settings,
    )


def test_build_pipeline_assembles_agents_in_sdd_6_2_order(db, test_settings):
    pipeline = _built_pipeline(db, test_settings)

    assert [agent.name for agent in pipeline] == [
        "user_query",
        "memory_read",
        "query_understanding",
        "retriever",
        "context_ranking",
        "prompt_construction",
        "llm",
        "response_validation",
        "citation",
    ]


def test_build_pipeline_short_circuits_via_a_real_agent_exception(db, seeded, test_settings):
    """Not a stub - a real, unmet precondition (no READY documents)
    surfaced by the real RetrieverAgent, proving build_pipeline's agents
    are genuinely wired to their repositories, not placeholders."""
    tenant_id, user_id = seeded
    pipeline = _built_pipeline(db, test_settings)
    context = QueryContext(
        request_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        raw_question="How many casual leaves do I get?",
    )

    with pytest.raises(NoDocumentsIndexedError):
        run_pipeline(pipeline, context)


def test_build_memory_write_agent_persists_the_turn_and_sets_message_id(db, seeded, test_settings):
    tenant_id, user_id = seeded
    session = SessionRepository(db).create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    agent = build_memory_write_agent(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        citation_repo=MessageCitationRepository(db),
        llm_service=FakeLLMService(),
        settings=test_settings,
    )
    context = QueryContext(
        request_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        raw_question="How many casual leaves do I get?",
        final_answer="Twelve days. HR remains the final authority.",
        confidence=ConfidenceLevel.HIGH,
    )

    result = agent.run(context)

    assert result.assistant_message_id is not None
    messages = MessageRepository(db).list_for_session(session.id)
    assert [m.id for m in messages if m.role.value == "assistant"] == [result.assistant_message_id]


# --- Fault injection through the real pipeline (SDD §6.4 doctrine; P6 exit
# criterion "fail-closed behavior demonstrated by fault injection"). Each
# test uses build_pipeline()'s genuine, dependency-injected agents - only
# the two true external I/O boundaries (the ChromaDB call inside Retriever,
# and the Gemini call inside LLMAgent/QueryUnderstanding) are faked, exactly
# as they are everywhere else in this suite. Everything in between,
# including the specific agent being fault-injected, is the real
# production class - proving the doctrine holds when agents actually run
# in sequence and hand real state to each other, not just in isolation. ---


def _ready_document(document_repo: DocumentRepository, tenant_id: uuid.UUID, user_id: uuid.UUID):
    return document_repo.create(
        tenant_id=tenant_id,
        uploaded_by=user_id,
        file_name="policy.pdf",
        display_name="policy.pdf",
        storage_path="uploads/policy.pdf",
        content_hash="a" * 64,
        size_bytes=10,
        status=DocumentStatus.READY,
    )


def _canned_chunks() -> list[RetrievedChunk]:
    return [
        RetrievedChunk(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_name="policy.pdf",
            page_start=1,
            page_end=1,
            section_title="Leave Policy",
            text="Employees receive twelve days of casual leave per year.",
            score=0.9,
        )
    ]


def test_fault_injection_response_validation_crash_fails_closed_through_real_pipeline(
    db, seeded, test_settings, monkeypatch: pytest.MonkeyPatch
):
    tenant_id, user_id = seeded
    document_repo = DocumentRepository(db)
    _ready_document(document_repo, tenant_id, user_id)
    monkeypatch.setattr(
        "app.rag.retriever.retrieve", lambda question, *, tenant_id, settings: _canned_chunks()
    )

    import app.agents.response_validator as response_validator_module

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated validator crash")

    monkeypatch.setattr(response_validator_module, "_extract_claims", _raise)

    pipeline = build_pipeline(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        document_repo=document_repo,
        llm_service=FakeLLMService(),
        settings=test_settings,
    )
    context = QueryContext(
        request_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        raw_question="How many casual leaves do I get?",
    )

    result = run_pipeline(pipeline, context)

    assert result.stage_statuses["response_validation"] == "failed"
    assert result.short_circuit_reason == "response_validation_failed"
    assert result.not_found is True
    assert result.confidence == ConfidenceLevel.NOT_FOUND
    assert "contact HR" in result.final_answer


def test_fault_injection_memory_read_crash_fails_soft_through_real_pipeline(
    db, seeded, test_settings, monkeypatch: pytest.MonkeyPatch
):
    """session_id=None means UserQueryAgent creates the session via
    SessionRepository.create(), never .get() - so the first real .get()
    call anywhere in the pipeline belongs to MemoryReadAgent, letting this
    monkeypatch target it exclusively without also breaking UserQueryAgent."""
    tenant_id, user_id = seeded
    document_repo = DocumentRepository(db)
    _ready_document(document_repo, tenant_id, user_id)
    monkeypatch.setattr(
        "app.rag.retriever.retrieve", lambda question, *, tenant_id, settings: _canned_chunks()
    )

    def _raise(*args, **kwargs):
        raise RuntimeError("simulated DB outage")

    monkeypatch.setattr(SessionRepository, "get", _raise)

    pipeline = build_pipeline(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        document_repo=document_repo,
        llm_service=FakeLLMService(),
        settings=test_settings,
    )
    context = QueryContext(
        request_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        raw_question="How many casual leaves do I get?",
        session_id=None,
    )

    result = run_pipeline(pipeline, context)

    assert result.stage_statuses["memory_read"] == "degraded"
    assert result.memory_turns == []
    assert result.short_circuit_reason is None  # pipeline continued
    assert result.not_found is False
    assert result.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.LOW)
    assert len(result.citations) > 0


def test_fault_injection_query_understanding_rewrite_crash_fails_soft_through_real_pipeline(
    db, seeded, test_settings, monkeypatch: pytest.MonkeyPatch
):
    tenant_id, user_id = seeded
    document_repo = DocumentRepository(db)
    _ready_document(document_repo, tenant_id, user_id)
    monkeypatch.setattr(
        "app.rag.retriever.retrieve", lambda question, *, tenant_id, settings: _canned_chunks()
    )

    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    message_repo.create(session=session, role=MessageRole.USER, content="What is the leave policy?")
    message_repo.create(session=session, role=MessageRole.ASSISTANT, content="Twelve days a year.")

    def _respond(prompt: str) -> str:
        if "Follow-up question:" in prompt:
            raise RuntimeError("simulated rewrite failure")
        return _default_response(prompt)

    fake_llm = FakeLLMService(respond=_respond)
    pipeline = build_pipeline(
        session_repo=session_repo,
        message_repo=message_repo,
        document_repo=document_repo,
        llm_service=fake_llm,
        settings=test_settings,
    )
    context = QueryContext(
        request_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        user_id=user_id,
        raw_question="What about for interns?",
        session_id=session.id,
    )

    result = run_pipeline(pipeline, context)

    assert result.stage_statuses["query_understanding"] == "degraded"
    assert result.standalone_query == "What about for interns?"  # fell back to raw question
    assert result.short_circuit_reason is None  # pipeline continued
    assert result.not_found is False
    assert len(result.citations) > 0
