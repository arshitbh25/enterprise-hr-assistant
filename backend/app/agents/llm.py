"""LLM Agent (SDD Section 6.3.6) - thin wrapper.

Sole owner of the Gemini generation call, delegated entirely to
`app.services.llm_service.LLMService` (Phase 5, unchanged) - all
timeout/backoff/circuit-breaker/temperature logic already lives there.

Input: `context.prompt_text`. Output: `context.draft_answer`,
`context.llm_usage`.

Communication: Prompt Construction Agent -> this agent -> Response
Validation Agent.

Failure cases: none added here - `LLMService`'s own exceptions
(`LlmQuotaExceededError`, `LlmUnavailableError`, `GenerationTimeoutError`)
propagate unchanged, mapping to their existing HTTP statuses via the
global `DomainError` handler. The orchestrator adds no second retry layer.
"""

from app.agents.base import QueryContext, agent_stage
from app.services.llm_service import LLMService


class LLMAgent:
    name = "llm"

    def __init__(self, *, llm_service: LLMService) -> None:
        self._llm_service = llm_service

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            result = self._llm_service.generate(context.prompt_text)
            context.draft_answer = result.text
            context.llm_usage = {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
            }
        return context
