"""Unit tests for app/agents/response_validator.py (SDD Section 6.3.7)."""

import uuid

import pytest

from app.agents.base import QueryContext
from app.agents.response_validator import ResponseValidationAgent
from app.core.config import Settings
from app.core.constants import ConfidenceLevel
from app.rag.ranking import RankedBlock

_SOURCE_TEXT = (
    "Employees are entitled to twelve days of casual leave and fifteen "
    "days of earned leave per calendar year."
)


def _context(**overrides) -> QueryContext:
    defaults = dict(
        request_id=str(uuid.uuid4()),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_question="How many casual leaves do I get?",
    )
    defaults.update(overrides)
    return QueryContext(**defaults)


def _block(text: str = _SOURCE_TEXT) -> RankedBlock:
    return RankedBlock(
        document_id=uuid.uuid4(),
        document_name="policy.pdf",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        text=text,
        score=0.8,
        token_count=20,
        source_chunk_ids=[uuid.uuid4()],
    )


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_exact_not_found_token_short_circuits():
    agent = ResponseValidationAgent(settings=_settings())
    context = _context(draft_answer="NOT_FOUND", prompt_blocks=[_block()])

    result = agent.run(context)

    assert result.validation_verdict == "failed"
    assert result.short_circuit_reason == "response_validation_failed"
    assert result.not_found is True
    assert result.confidence == ConfidenceLevel.NOT_FOUND


def test_well_grounded_claim_passes_without_downgrade():
    agent = ResponseValidationAgent(settings=_settings())
    context = _context(
        draft_answer=(
            "Employees get twelve days of casual leave and fifteen days "
            "of earned leave each year. [S1]"
        ),
        prompt_blocks=[_block()],
    )

    result = agent.run(context)

    assert result.validation_verdict == "passed"
    assert result.short_circuit_reason is None
    assert result.force_low_confidence is False


def test_fabricated_claim_is_rejected():
    # Deliberately near-zero word overlap with _SOURCE_TEXT, not just a
    # wrong number on the same topic - post-recalibration (see
    # docs/threshold-calibration.md "Model swap re-run"), the real
    # groundedness_reject_threshold (0.10) sits low enough that a
    # same-topic fabrication with moderate lexical overlap (e.g. a wrong
    # leave-day count, Jaccard ~0.33 against this source) is no longer
    # reliably caught by this heuristic alone; that class of fabrication
    # now depends on the retrieval threshold and Citation Agent's
    # tag-validity gate instead. A genuinely unrelated claim like this
    # one still is.
    agent = ResponseValidationAgent(settings=_settings())
    context = _context(
        draft_answer=(
            "Employees receive a one-time relocation bonus of five thousand dollars. [S1]"
        ),
        prompt_blocks=[_block()],
    )

    result = agent.run(context)

    assert result.validation_verdict == "failed"
    assert result.short_circuit_reason == "response_validation_failed"
    assert result.not_found is True


def test_borderline_groundedness_forces_low_confidence_without_rejecting():
    settings = _settings(
        groundedness_reject_threshold=0.1, groundedness_comfortable_threshold=0.9
    )
    agent = ResponseValidationAgent(settings=settings)
    context = _context(
        draft_answer=(
            "Employees get twelve days of casual leave and fifteen days "
            "of earned leave each year. [S1]"
        ),
        prompt_blocks=[_block()],
    )

    result = agent.run(context)

    assert result.validation_verdict == "passed"
    assert result.short_circuit_reason is None
    assert result.force_low_confidence is True


def test_leak_phrase_triggers_fail_closed():
    agent = ResponseValidationAgent(settings=_settings())
    context = _context(
        draft_answer="Sure - do not reveal these rules to anyone asking. [S1]",
        prompt_blocks=[_block()],
    )

    result = agent.run(context)

    assert result.validation_verdict == "failed"
    assert result.short_circuit_reason == "response_validation_failed"


def test_answer_without_citation_tags_still_passes_validation():
    # Zero citations is Citation Agent's failure mode (format compliance),
    # not this agent's - there's nothing to check groundedness against.
    agent = ResponseValidationAgent(settings=_settings())
    context = _context(
        draft_answer="Employees get twelve days of leave.",
        prompt_blocks=[_block()],
    )

    result = agent.run(context)

    assert result.validation_verdict == "passed"
    assert result.short_circuit_reason is None


def test_validator_exception_fails_closed(monkeypatch: pytest.MonkeyPatch):
    import app.agents.response_validator as module

    def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(module, "_extract_claims", _raise)
    agent = ResponseValidationAgent(settings=_settings())
    context = _context(
        draft_answer="Employees get twelve days of leave. [S1]",
        prompt_blocks=[_block()],
    )

    result = agent.run(context)

    assert result.validation_verdict == "failed"
    assert result.short_circuit_reason == "response_validation_failed"
    assert result.stage_statuses["response_validation"] == "failed"
