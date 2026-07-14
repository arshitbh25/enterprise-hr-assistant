"""Query Understanding Agent (SDD Section 6.3.2).

Turns a conversational utterance into a retrieval-ready standalone
query. Scope classification runs first and is pure heuristic (no LLM
call), so off-topic/greeting questions short-circuit before spending
any retrieval or generation cost (FR-Q07) - deliberately conservative:
ambiguous questions default to "policy" and fall through to retrieval,
since a false "off_topic" would incorrectly block a real question (the
worse failure mode), while a false "policy" classification still gets
correctly rejected downstream by the retrieval threshold gate.

Only follow-up questions (non-empty memory + a pronoun/ellipsis
pattern) trigger a small Gemini rewrite call - first-turn questions
pass through rewrite-free, saving quota/latency (SDD 6.3.2 exactly).
Rewrite failure of any kind falls back to the raw question (fail soft,
logged as degraded) rather than blocking the turn.

Input: `context.raw_question`, `context.memory_turns`. Output:
`context.standalone_query`, `context.scope`, or (off_topic/greeting)
`context.short_circuit_reason` + the canned response.

Communication: Memory Agent (read path) -> this agent -> Retriever Agent.

Failure cases: rewrite LLM call fails -> fall back to raw question,
degraded, logged; off-topic -> short-circuit to a polite scope refusal
without spending retrieval/generation.

Templates load once at process startup (`init_rewrite_template()`,
called from `app.main`'s lifespan) - mirrors the exact pattern
`app.rag.prompt_builder` already uses for the answer template.
"""

import re
import string
from pathlib import Path

from app.agents.base import QueryContext, agent_stage, format_memory_turns
from app.core.constants import GREETING_RESPONSE_MESSAGE, SCOPE_REFUSAL_MESSAGE, ConfidenceLevel
from app.core.logging import get_logger
from app.services.llm_service import LLMService

logger = get_logger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_REWRITE_TEMPLATE_NAME = "rewrite_v1.txt"

_rewrite_template: string.Template | None = None


def init_rewrite_template() -> None:
    """Load and cache the rewrite template. Called once from the app
    lifespan; raises (fails boot) if the file is missing or unreadable."""
    global _rewrite_template
    path = _PROMPTS_DIR / _REWRITE_TEMPLATE_NAME
    _rewrite_template = string.Template(path.read_text(encoding="utf-8"))


def get_rewrite_template() -> string.Template:
    if _rewrite_template is None:
        init_rewrite_template()
    assert _rewrite_template is not None
    return _rewrite_template


_FOLLOWUP_LEAD_RE = re.compile(r"^\s*(what about|and (for|about)|how about)\b", re.IGNORECASE)
_PRONOUN_RE = re.compile(r"\b(it|this|that|they|them|those|these)\b", re.IGNORECASE)

_GREETING_RE = re.compile(
    r"^\s*(hi|hello|hey|good (morning|afternoon|evening)|greetings)[\s!.,]*$", re.IGNORECASE
)
_OFF_TOPIC_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bwrite (a|me a|some)?\s*(python|code|function|program|poem|song|story)\b",
        r"\bwhat is the capital of\b",
        r"\bwho won\b.*\b(world cup|election|game)\b",
        r"\bboiling point\b",
        r"\bsolve\b.*\b(equation|math)\b",
        r"^\s*\d+\s*[+\-*/]\s*\d+",
    )
]

# SDD 6.3.2: "light query expansion (acronym normalization from a
# configurable glossary)". A small in-code dict rather than a settings-
# driven list - easily extended, no runtime configurability needed yet.
_ACRONYM_GLOSSARY = {
    "pto": "paid time off",
    "wfh": "work from home",
    "posh": "prevention of sexual harassment",
    "ctc": "cost to company",
}
_ACRONYM_RE = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in _ACRONYM_GLOSSARY) + r")\b", re.IGNORECASE
)


def _classify_scope(question: str) -> str:
    if _GREETING_RE.match(question):
        return "greeting"
    if any(pattern.search(question) for pattern in _OFF_TOPIC_PATTERNS):
        return "off_topic"
    return "policy"


def _looks_like_follow_up(question: str) -> bool:
    if _FOLLOWUP_LEAD_RE.search(question):
        return True
    return bool(_PRONOUN_RE.search(question)) and len(question.split()) <= 8


def _expand_acronyms(text: str) -> str:
    return _ACRONYM_RE.sub(lambda match: _ACRONYM_GLOSSARY[match.group(0).lower()], text)


class QueryUnderstandingAgent:
    name = "query_understanding"

    def __init__(self, *, llm_service: LLMService) -> None:
        self._llm_service = llm_service

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            scope = _classify_scope(context.raw_question)
            context.scope = scope

            if scope == "greeting":
                context.short_circuit_reason = "greeting"
                context.final_answer = GREETING_RESPONSE_MESSAGE
                context.confidence = ConfidenceLevel.NOT_FOUND
                context.not_found = True
                return context

            if scope == "off_topic":
                context.short_circuit_reason = "off_topic"
                context.final_answer = SCOPE_REFUSAL_MESSAGE
                context.confidence = ConfidenceLevel.NOT_FOUND
                context.not_found = True
                return context

            standalone_query = context.raw_question
            if context.memory_turns and _looks_like_follow_up(context.raw_question):
                try:
                    prompt = get_rewrite_template().substitute(
                        history=format_memory_turns(context.memory_turns),
                        question=context.raw_question,
                    )
                    rewritten = self._llm_service.generate(prompt).text.strip()
                    if rewritten:
                        standalone_query = rewritten
                except Exception as exc:  # noqa: BLE001 - fail soft: keep the raw question
                    context.stage_statuses[self.name] = "degraded"
                    logger.warning(
                        "query_rewrite_failed", request_id=context.request_id, exc_info=exc
                    )

            context.standalone_query = _expand_acronyms(standalone_query)

        return context
