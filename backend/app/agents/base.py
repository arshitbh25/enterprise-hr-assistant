"""Agent contract (SDD Section 6.1): the typed, append-only QueryContext
passed through the pipeline, and the Agent protocol every stage
implements.

"Agent" means a single-responsibility, independently testable pipeline
stage with a typed contract - not an autonomous LLM free-running with
tools (SDD 6.1). Only three stages ever call the LLM (Query
Understanding for rewrites, LLM Agent for generation, Memory Agent for
summary refresh); everything else is plain code.

"Append-only" is a convention, not a Pydantic-enforced constraint: each
agent only ever writes the field(s) it owns and never overwrites what
an earlier agent already set. QueryContext is deliberately mutable (a
plain Pydantic BaseModel) since the whole point is progressively
filling in one shared object across a sequential pipeline (SDD 6.2) -
the discipline is enforced by each agent's own tests, not by
immutability. The fully populated context is what the final audit log
record (Module 7) is built from.
"""

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import ConfidenceLevel
from app.core.logging import get_logger
from app.rag.citations import Citation
from app.rag.ranking import RankedBlock
from app.rag.retriever import RetrievedChunk

logger = get_logger(__name__)

Scope = Literal["policy", "greeting", "off_topic"]


class MemoryTurn(BaseModel):
    """One prior user+assistant exchange, as read back by the Memory
    Agent (SDD 6.3.9) - the condensed shape of a pair of `messages` rows."""

    question: str
    answer: str


def format_memory_turns(turns: list[MemoryTurn]) -> str:
    """Condensed 'Q: ... / A: ...' text block, shared by Query
    Understanding (rewrite prompts) and Memory (summarization prompts) -
    both need the exact same turn-to-text rendering."""
    return "\n".join(f"Q: {turn.question}\nA: {turn.answer}" for turn in turns)


class QueryContext(BaseModel):
    """Shared state threaded through the whole agent pipeline (SDD 6.1).
    Fields are grouped below by which agent writes them - see each
    agent's own module docstring (Module 3+) for its exact
    responsibility/input/output/failure-handling contract."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # --- Set at construction (chat.py), before any agent runs ---
    request_id: str
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    raw_question: str

    # --- User Query Agent ---
    session_id: uuid.UUID | None = None
    suspicious: bool = False

    # --- Memory Agent (read path) ---
    memory_turns: list[MemoryTurn] = Field(default_factory=list)
    memory_summary: str | None = None

    # --- Query Understanding Agent ---
    standalone_query: str | None = None
    scope: Scope | None = None
    clarification_needed: bool = False

    # --- Retriever Agent ---
    retrieved_chunks: list[RetrievedChunk] = Field(default_factory=list)

    # --- Context Ranking Agent ---
    ranked_blocks: list[RankedBlock] = Field(default_factory=list)

    # --- Prompt Construction Agent ---
    prompt_text: str | None = None
    prompt_blocks: list[RankedBlock] = Field(default_factory=list)

    # --- LLM Agent ---
    draft_answer: str | None = None
    llm_usage: dict[str, int] | None = None

    # --- Response Validation Agent ---
    validation_verdict: Literal["passed", "failed", "not_applicable"] | None = None
    # Borderline groundedness forces confidence down without failing the
    # turn outright - Citation Agent computes its own confidence from the
    # retrieval score afterward, so it must read and respect this cap
    # rather than blindly overwriting it.
    force_low_confidence: bool = False

    # --- Citation Agent ---
    citations: list[Citation] = Field(default_factory=list)

    # --- Memory Agent (write path) ---
    assistant_message_id: uuid.UUID | None = None

    # --- Final response, written by whichever agent finalizes the turn
    # (Context Ranking on empty result, Query Understanding on scope
    # short-circuit, Response Validation on failure, or Citation Agent
    # on a genuine answer) ---
    final_answer: str | None = None
    confidence: ConfidenceLevel | None = None
    not_found: bool = False

    # --- Orchestrator control: any agent may set this to stop the
    # pipeline early; the orchestrator checks it after every stage ---
    short_circuit_reason: str | None = None

    # --- Logging Agent data (SDD 6.3.10), written by agent_stage() below ---
    stage_timings: dict[str, int] = Field(default_factory=dict)
    stage_statuses: dict[str, str] = Field(default_factory=dict)


class Agent(Protocol):
    name: str

    def run(self, context: QueryContext) -> QueryContext: ...


@contextmanager
def agent_stage(context: QueryContext, agent_name: str) -> Iterator[None]:
    """The Logging Agent's implementation (SDD 6.3.10: "middleware + a
    context-manager each agent enters" - request-id correlation is
    already provided by the existing RequestIDMiddleware, so this only
    adds the per-agent piece). Every agent wraps its run() body in this.

    Records duration into context.stage_timings and emits one
    structured event per stage. On a genuine exception, marks the stage
    "failed" and re-raises unchanged - this wrapper never swallows a
    real error; fail-soft degradation is each agent's own decision
    (it should set context.stage_statuses[agent_name] = "degraded"
    itself before returning, which this context manager will not
    overwrite). All logging is wrapped in its own try/except - logging
    must never break the request path (SDD 6.3.10's own failure case).
    """
    started_at = time.perf_counter()
    try:
        yield
    except Exception:
        context.stage_statuses[agent_name] = "failed"
        raise
    else:
        context.stage_statuses.setdefault(agent_name, "ok")
    finally:
        duration_ms = round((time.perf_counter() - started_at) * 1000)
        context.stage_timings[agent_name] = duration_ms
        try:
            logger.info(
                "agent_stage_completed",
                request_id=context.request_id,
                agent=agent_name,
                duration_ms=duration_ms,
                status=context.stage_statuses.get(agent_name, "ok"),
            )
        except Exception:  # noqa: BLE001 - logging must never break the request path
            pass
