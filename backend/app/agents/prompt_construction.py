"""Prompt Construction Agent (SDD Section 6.3.5) - thin wrapper.

Delegates to `app.rag.prompt_builder.build_prompt()`, now passing the
condensed conversation history (Module 7: Memory Agent's read-path
output, `context.memory_summary` + `context.memory_turns`) through the
new `history` parameter - the rolling summary (if any) comes first as
older context, then the verbatim recent turns, using the exact same
`format_memory_turns()` rendering Query Understanding's rewrite prompt
already uses (SDD 6.3.9: "one condensed 'Q: ... / A: ...' text block").

Input: `context.standalone_query` (falls back to `raw_question`),
`context.ranked_blocks`, `context.memory_summary`, `context.memory_turns`.
Output: `context.prompt_text`, `context.prompt_blocks` (the blocks
actually used after any token-budget trim - may be fewer than
`ranked_blocks`).

Communication: Context Ranking Agent -> this agent -> LLM Agent.

Failure cases: none of its own - a missing template fails at boot
(`init_prompt_templates()`, `app.main`'s lifespan), not at request time.
"""

from app.agents.base import QueryContext, agent_stage, format_memory_turns
from app.core.config import Settings
from app.rag import prompt_builder


def _condensed_history(context: QueryContext) -> str:
    parts = []
    if context.memory_summary:
        parts.append(f"Summary of earlier conversation: {context.memory_summary}")
    if context.memory_turns:
        parts.append(format_memory_turns(context.memory_turns))
    return "\n\n".join(parts)


class PromptConstructionAgent:
    name = "prompt_construction"

    def __init__(self, *, settings: Settings) -> None:
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            question = context.standalone_query or context.raw_question
            built = prompt_builder.build_prompt(
                question,
                context.ranked_blocks,
                history=_condensed_history(context),
                settings=self._settings,
            )
            context.prompt_text = built.text
            context.prompt_blocks = built.blocks
        return context
