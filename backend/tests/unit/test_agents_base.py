"""Unit tests for app/agents/base.py (SDD Section 6.1, 6.3.10)."""

import uuid

import pytest
from pydantic import ValidationError

from app.agents.base import QueryContext, agent_stage


def _context(**overrides) -> QueryContext:
    defaults = dict(
        request_id=str(uuid.uuid4()),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_question="How many casual leaves do I get?",
    )
    defaults.update(overrides)
    return QueryContext(**defaults)


def test_query_context_defaults():
    context = _context()

    assert context.session_id is None
    assert context.suspicious is False
    assert context.memory_turns == []
    assert context.memory_summary is None
    assert context.standalone_query is None
    assert context.scope is None
    assert context.retrieved_chunks == []
    assert context.ranked_blocks == []
    assert context.citations == []
    assert context.not_found is False
    assert context.short_circuit_reason is None
    assert context.stage_timings == {}
    assert context.stage_statuses == {}


def test_query_context_requires_core_identity_fields():
    with pytest.raises(ValidationError):
        QueryContext()  # missing request_id/tenant_id/user_id/raw_question


def test_agent_stage_records_timing_and_defaults_to_ok():
    context = _context()

    with agent_stage(context, "test_stage"):
        pass

    assert context.stage_statuses["test_stage"] == "ok"
    assert context.stage_timings["test_stage"] >= 0


def test_agent_stage_preserves_a_status_the_agent_already_set():
    context = _context()

    with agent_stage(context, "test_stage"):
        context.stage_statuses["test_stage"] = "degraded"

    assert context.stage_statuses["test_stage"] == "degraded"
    assert "test_stage" in context.stage_timings


def test_agent_stage_marks_failed_and_reraises_on_exception():
    context = _context()

    with pytest.raises(RuntimeError):
        with agent_stage(context, "test_stage"):
            raise RuntimeError("boom")

    assert context.stage_statuses["test_stage"] == "failed"
    assert "test_stage" in context.stage_timings


def test_agent_stage_logging_failure_never_breaks_the_request_path(
    monkeypatch: pytest.MonkeyPatch,
):
    import app.agents.base as base_module

    def _raise(*args, **kwargs):
        raise RuntimeError("log sink is down")

    monkeypatch.setattr(base_module.logger, "info", _raise)
    context = _context()

    with agent_stage(context, "test_stage"):
        pass  # must not raise despite the logging failure above

    assert context.stage_statuses["test_stage"] == "ok"
    assert "test_stage" in context.stage_timings
