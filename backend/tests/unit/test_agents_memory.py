"""Unit tests for app/agents/memory.py (SDD Section 6.3.9, FR-S05)."""

import uuid

import pytest

from app.agents.base import QueryContext
from app.agents.memory import MemoryReadAgent, MemoryWriteAgent, init_summarize_template
from app.core.constants import ConfidenceLevel, MessageRole
from app.database.repositories.message_citations import MessageCitationRepository
from app.database.repositories.messages import MessageRepository
from app.database.repositories.sessions import SessionRepository
from app.rag.citations import Citation
from tests._fakes import FakeLLMService


def _context(**overrides) -> QueryContext:
    defaults = dict(
        request_id=str(uuid.uuid4()),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_question="How many casual leaves do I get?",
    )
    defaults.update(overrides)
    return QueryContext(**defaults)


@pytest.fixture(autouse=True)
def _reset_template_cache():
    init_summarize_template()
    yield
    init_summarize_template()


def _add_turn(message_repo, session, question: str, answer: str) -> None:
    message_repo.create(session=session, role=MessageRole.USER, content=question)
    message_repo.create(session=session, role=MessageRole.ASSISTANT, content=answer)


# --- MemoryReadAgent ---


def test_memory_read_returns_empty_for_a_brand_new_session(db, seeded, test_settings):
    tenant_id, user_id = seeded
    session = SessionRepository(db).create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    agent = MemoryReadAgent(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        settings=test_settings,
    )

    result = agent.run(
        _context(tenant_id=tenant_id, user_id=user_id, session_id=session.id)
    )

    assert result.memory_turns == []
    assert result.memory_summary is None


def test_memory_read_returns_prior_turns_and_summary(db, seeded, test_settings):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    _add_turn(message_repo, session, "What is the leave policy?", "Twelve days a year.")
    session_repo.update_summary(session, "Discussed leave policy.")

    agent = MemoryReadAgent(
        session_repo=session_repo, message_repo=message_repo, settings=test_settings
    )
    result = agent.run(
        _context(tenant_id=tenant_id, user_id=user_id, session_id=session.id)
    )

    assert len(result.memory_turns) == 1
    assert result.memory_turns[0].question == "What is the leave policy?"
    assert result.memory_turns[0].answer == "Twelve days a year."
    assert result.memory_summary == "Discussed leave policy."


def test_memory_read_respects_the_window_size(db, seeded):
    from app.core.config import Settings

    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    for i in range(5):
        _add_turn(message_repo, session, f"Question {i}", f"Answer {i}")

    settings = Settings(_env_file=None, memory_window_turns=2)
    agent = MemoryReadAgent(session_repo=session_repo, message_repo=message_repo, settings=settings)
    result = agent.run(
        _context(tenant_id=tenant_id, user_id=user_id, session_id=session.id)
    )

    assert len(result.memory_turns) == 2
    assert result.memory_turns[0].question == "Question 3"
    assert result.memory_turns[1].question == "Question 4"


def test_memory_read_failure_degrades_to_memory_less(db, seeded, test_settings):
    tenant_id, user_id = seeded
    agent = MemoryReadAgent(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        settings=test_settings,
    )

    # session_id references nothing real -> session_repo.get() returns None
    result = agent.run(
        _context(tenant_id=tenant_id, user_id=user_id, session_id=uuid.uuid4())
    )

    assert result.memory_turns == []
    assert result.memory_summary is None
    assert result.stage_statuses["memory_read"] == "degraded"


# --- MemoryWriteAgent ---


def _write_agent(db, settings, llm_service=None) -> MemoryWriteAgent:
    return MemoryWriteAgent(
        session_repo=SessionRepository(db),
        message_repo=MessageRepository(db),
        citation_repo=MessageCitationRepository(db),
        llm_service=llm_service or FakeLLMService(),
        settings=settings,
    )


def test_memory_write_persists_user_and_assistant_messages_with_citations(
    db, seeded, test_settings
):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    citation = Citation(
        chunk_id=uuid.uuid4(),
        document_name="policy.pdf",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        snippet="Employees get twelve days of leave.",
    )
    agent = _write_agent(db, test_settings)

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        raw_question="How many leaves?",
        standalone_query="How many casual leaves do I get?",
        final_answer="Twelve days. HR remains the final authority.",
        confidence=ConfidenceLevel.HIGH,
        citations=[citation],
        llm_usage={"prompt_tokens": 100, "completion_tokens": 20},
    )

    agent.run(context)

    messages = MessageRepository(db).list_for_session(session.id)
    assert len(messages) == 2
    assert messages[0].role == MessageRole.USER
    assert messages[0].content == "How many leaves?"
    assert messages[0].standalone_query == "How many casual leaves do I get?"
    assert messages[1].role == MessageRole.ASSISTANT
    assert messages[1].content == "Twelve days. HR remains the final authority."
    assert messages[1].confidence == ConfidenceLevel.HIGH
    assert messages[1].prompt_tokens == 100
    assert messages[1].completion_tokens == 20


def test_memory_write_persists_a_not_found_turn(db, seeded, test_settings):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    agent = _write_agent(db, test_settings)

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        raw_question="What is the capital of France?",
        final_answer="I could not find this in the uploaded HR policy documents.",
        confidence=ConfidenceLevel.NOT_FOUND,
        not_found=True,
        short_circuit_reason="off_topic",
    )

    agent.run(context)

    messages = MessageRepository(db).list_for_session(session.id)
    assert len(messages) == 2
    assert messages[1].content == "I could not find this in the uploaded HR policy documents."
    assert messages[1].confidence == ConfidenceLevel.NOT_FOUND


def test_memory_write_sets_title_from_first_question(db, seeded, test_settings):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    agent = _write_agent(db, test_settings)

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        raw_question="How many casual leaves do I get?",
        final_answer="Twelve days.",
        confidence=ConfidenceLevel.HIGH,
    )
    agent.run(context)

    refreshed = session_repo.get(tenant_id, user_id, session.id)
    assert refreshed.title == "How many casual leaves do I get?"


def test_memory_write_truncates_a_long_title(db, seeded):
    from app.core.config import Settings

    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)

    settings = Settings(_env_file=None, session_title_max_chars=20)
    agent = MemoryWriteAgent(
        session_repo=session_repo,
        message_repo=MessageRepository(db),
        citation_repo=MessageCitationRepository(db),
        llm_service=FakeLLMService(),
        settings=settings,
    )

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        raw_question="How many casual leaves do I get per calendar year as a new employee?",
        final_answer="Twelve days.",
        confidence=ConfidenceLevel.HIGH,
    )
    agent.run(context)

    refreshed = session_repo.get(tenant_id, user_id, session.id)
    assert refreshed.title == "How many casual lea…"
    assert len(refreshed.title) == 20


def test_memory_write_does_not_overwrite_an_existing_title(db, seeded, test_settings):
    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    session_repo.update_title(session, "Original title")
    agent = _write_agent(db, test_settings)

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        raw_question="A follow-up question",
        final_answer="A follow-up answer.",
        confidence=ConfidenceLevel.HIGH,
    )
    agent.run(context)

    refreshed = session_repo.get(tenant_id, user_id, session.id)
    assert refreshed.title == "Original title"


def test_memory_write_triggers_summary_refresh_at_the_configured_interval(db, seeded):
    from app.core.config import Settings

    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)

    settings = Settings(_env_file=None, memory_summary_refresh_interval_turns=1)
    fake_llm = FakeLLMService(respond=lambda prompt: "Discussed leave policy in detail.")
    agent = MemoryWriteAgent(
        session_repo=session_repo,
        message_repo=message_repo,
        citation_repo=MessageCitationRepository(db),
        llm_service=fake_llm,
        settings=settings,
    )

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        final_answer="Twelve days.",
        confidence=ConfidenceLevel.HIGH,
    )
    agent.run(context)

    refreshed = session_repo.get(tenant_id, user_id, session.id)
    assert refreshed.summary == "Discussed leave policy in detail."
    assert len(fake_llm.calls) == 1


def test_memory_write_does_not_refresh_summary_before_interval_reached(db, seeded):
    from app.core.config import Settings

    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)

    settings = Settings(_env_file=None, memory_summary_refresh_interval_turns=6)
    fake_llm = FakeLLMService()
    agent = MemoryWriteAgent(
        session_repo=session_repo,
        message_repo=message_repo,
        citation_repo=MessageCitationRepository(db),
        llm_service=fake_llm,
        settings=settings,
    )

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        final_answer="Twelve days.",
        confidence=ConfidenceLevel.HIGH,
    )
    agent.run(context)  # first turn: turn_count == 1, interval == 6 -> no refresh

    assert fake_llm.calls == []
    refreshed = session_repo.get(tenant_id, user_id, session.id)
    assert refreshed.summary is None


def test_memory_write_summary_refresh_failure_keeps_previous_summary(db, seeded):
    from app.core.config import Settings

    tenant_id, user_id = seeded
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)
    session = session_repo.create(tenant_id=tenant_id, user_id=user_id, ttl_hours=24)
    session_repo.update_summary(session, "Original summary.")

    settings = Settings(_env_file=None, memory_summary_refresh_interval_turns=1)
    fake_llm = FakeLLMService()
    fake_llm.raise_error = RuntimeError("simulated Gemini failure")
    agent = MemoryWriteAgent(
        session_repo=session_repo,
        message_repo=message_repo,
        citation_repo=MessageCitationRepository(db),
        llm_service=fake_llm,
        settings=settings,
    )

    context = _context(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session.id,
        final_answer="Twelve days.",
        confidence=ConfidenceLevel.HIGH,
    )
    agent.run(context)  # must not raise despite the summary-refresh failure

    refreshed = session_repo.get(tenant_id, user_id, session.id)
    assert refreshed.summary == "Original summary."
