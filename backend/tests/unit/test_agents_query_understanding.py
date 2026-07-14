"""Unit tests for app/agents/query_understanding.py (SDD Section 6.3.2)."""

import uuid

import pytest

from app.agents.base import MemoryTurn, QueryContext
from app.agents.query_understanding import QueryUnderstandingAgent, init_rewrite_template
from app.core.constants import ConfidenceLevel
from app.services.llm_service import LLMResult
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
    init_rewrite_template()
    yield
    init_rewrite_template()


def test_greeting_short_circuits_without_calling_the_llm():
    fake = FakeLLMService()
    agent = QueryUnderstandingAgent(llm_service=fake)

    result = agent.run(_context(raw_question="Hello!"))

    assert result.scope == "greeting"
    assert result.short_circuit_reason == "greeting"
    assert result.not_found is True
    assert result.confidence == ConfidenceLevel.NOT_FOUND
    assert fake.calls == []


def test_off_topic_short_circuits_without_calling_the_llm():
    fake = FakeLLMService()
    agent = QueryUnderstandingAgent(llm_service=fake)

    result = agent.run(_context(raw_question="What is the capital of France?"))

    assert result.scope == "off_topic"
    assert result.short_circuit_reason == "off_topic"
    assert result.not_found is True
    assert fake.calls == []


def test_ambiguous_question_defaults_to_policy_scope():
    fake = FakeLLMService()
    agent = QueryUnderstandingAgent(llm_service=fake)

    result = agent.run(_context(raw_question="Can I carry forward my earned leave?"))

    assert result.scope == "policy"
    assert result.short_circuit_reason is None


def test_first_turn_question_passes_through_without_rewrite():
    fake = FakeLLMService()
    agent = QueryUnderstandingAgent(llm_service=fake)

    result = agent.run(_context(raw_question="What is the casual leave policy?"))

    assert result.standalone_query == "What is the casual leave policy?"
    assert fake.calls == []  # zero LLM cost on first-turn questions


def test_follow_up_with_memory_triggers_a_rewrite_call():
    fake = FakeLLMService(respond=lambda prompt: "What is the leave policy for interns?")
    agent = QueryUnderstandingAgent(llm_service=fake)
    memory = [MemoryTurn(question="What is the leave policy?", answer="Twelve days a year.")]

    result = agent.run(
        _context(raw_question="What about for interns?", memory_turns=memory)
    )

    assert result.standalone_query == "What is the leave policy for interns?"
    assert len(fake.calls) == 1
    assert "What about for interns?" in fake.calls[0]


def test_question_with_memory_but_no_follow_up_pattern_does_not_rewrite():
    fake = FakeLLMService()
    agent = QueryUnderstandingAgent(llm_service=fake)
    memory = [MemoryTurn(question="What is the leave policy?", answer="Twelve days a year.")]

    result = agent.run(
        _context(raw_question="What is the dress code policy?", memory_turns=memory)
    )

    assert result.standalone_query == "What is the dress code policy?"
    assert fake.calls == []


def test_rewrite_failure_falls_back_to_raw_question_and_marks_degraded():
    fake = FakeLLMService()
    fake.raise_error = RuntimeError("simulated Gemini failure")
    agent = QueryUnderstandingAgent(llm_service=fake)
    memory = [MemoryTurn(question="What is the leave policy?", answer="Twelve days a year.")]

    result = agent.run(
        _context(raw_question="What about for interns?", memory_turns=memory)
    )

    assert result.standalone_query == "What about for interns?"
    assert result.stage_statuses["query_understanding"] == "degraded"
    assert result.short_circuit_reason is None  # fail soft, not fail closed


def test_rewrite_returning_empty_text_falls_back_to_raw_question():
    fake = FakeLLMService(respond=lambda prompt: "   ")
    agent = QueryUnderstandingAgent(llm_service=fake)
    memory = [MemoryTurn(question="What is the leave policy?", answer="Twelve days a year.")]

    result = agent.run(
        _context(raw_question="What about for interns?", memory_turns=memory)
    )

    assert result.standalone_query == "What about for interns?"


def test_acronym_expansion_is_applied_to_the_standalone_query():
    fake = FakeLLMService()
    agent = QueryUnderstandingAgent(llm_service=fake)

    result = agent.run(_context(raw_question="What is the PTO policy?"))

    assert "paid time off" in result.standalone_query.lower()


def test_llm_agent_result_is_a_real_llmresult_type():
    # sanity check that FakeLLMService.generate() still returns the real
    # LLMResult dataclass the agent expects, keeping the fake a faithful
    # stand-in for the Protocol.
    fake = FakeLLMService()
    result = fake.generate("prompt")
    assert isinstance(result, LLMResult)
