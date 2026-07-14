"""Citation Agent (SDD Section 6.3.8) - thin wrapper.

Delegates to `app.rag.citations.process_answer()` (Phase 5, unchanged),
which already covers format compliance (tag validity) and refusal
compliance (NOT_FOUND normalization). Response Validation Agent (Module
6) adds the groundedness/leak checks on top and runs *before* this
agent, so by the time this agent sees the draft answer it has already
passed those checks - this agent's own tag-validity check is a harmless
second layer (same defense-in-depth pattern as the threshold + validation
double-gate elsewhere in this pipeline). It also respects
`context.force_low_confidence` - Response Validation's borderline-
groundedness downgrade - since `process_answer()`'s own confidence
(computed from the retrieval score alone) would otherwise silently
overwrite it.

Input: `context.draft_answer`, `context.prompt_blocks`. Output:
`context.citations`, `context.final_answer`, `context.confidence`,
`context.not_found` (or, on a citation-integrity failure,
`short_circuit_reason` - the same fail-closed NOT_FOUND behavior Phase
5 already had, just now expressed via the shared context field).

Communication: Response Validation Agent -> this agent -> Memory Agent
(write path, which runs unconditionally after this - even a NOT_FOUND
turn is persisted, matching Phase 5's existing behavior) -> back to the
user.

Failure cases: none of its own beyond what `process_answer()` already
handles (any invalid/missing citation tag -> NOT_FOUND, fail closed).
"""

from app.agents.base import QueryContext, agent_stage
from app.core.config import Settings
from app.core.constants import HR_DISCLAIMER, STANDARD_NOT_FOUND_MESSAGE, ConfidenceLevel
from app.rag import citations as rag_citations


class CitationAgent:
    name = "citation"

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            result = rag_citations.process_answer(
                context.draft_answer, context.prompt_blocks, settings=self._settings
            )
            context.citations = result.citations
            context.confidence = result.confidence
            context.not_found = result.not_found
            if result.not_found:
                context.short_circuit_reason = "citation_validation_failed"
                context.final_answer = f"{STANDARD_NOT_FOUND_MESSAGE} {HR_DISCLAIMER}"
            else:
                context.final_answer = f"{result.answer_text} {HR_DISCLAIMER}"
                if context.force_low_confidence and context.confidence == ConfidenceLevel.HIGH:
                    context.confidence = ConfidenceLevel.LOW
        return context
