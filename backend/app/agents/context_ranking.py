"""Context Ranking Agent (SDD Section 6.3.4) - thin wrapper.

Delegates to `app.rag.ranking.rank_chunks()` (Phase 5, unchanged). An
empty result is the primary anti-hallucination gate: weak context must
never reach the LLM, so this agent sets `short_circuit_reason` and
writes the standard NOT_FOUND response directly onto the context (SDD
6.4: "fail closed on truthfulness").

Input: `context.retrieved_chunks`. Output: `context.ranked_blocks`, or
(on empty) `context.short_circuit_reason`/`final_answer`/`confidence`/
`not_found`.

Communication: Retriever Agent -> this agent -> Prompt Construction Agent.

Failure cases: nothing survives the threshold -> NOT_FOUND (fail
closed, this agent's only failure mode). `rank_chunks()` itself has no
internal fail-soft fallback (Phase 5 never built one), so an unexpected
exception here is a genuine bug and propagates like any other agent's
crash - not silently degraded.
"""

from app.agents.base import QueryContext, agent_stage
from app.core.config import Settings
from app.core.constants import HR_DISCLAIMER, STANDARD_NOT_FOUND_MESSAGE, ConfidenceLevel
from app.rag import ranking


class ContextRankingAgent:
    name = "context_ranking"

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            context.ranked_blocks = ranking.rank_chunks(
                context.retrieved_chunks, settings=self._settings
            )
            if not context.ranked_blocks:
                context.short_circuit_reason = "no_context_above_threshold"
                context.final_answer = f"{STANDARD_NOT_FOUND_MESSAGE} {HR_DISCLAIMER}"
                context.confidence = ConfidenceLevel.NOT_FOUND
                context.not_found = True
        return context
