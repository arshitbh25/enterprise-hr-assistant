"""Prompt Construction Agent (SDD Section 6.3.5, Section 7.2 Stage 9, Section 11.1).

Assembles the final prompt from the versioned answer_v1.txt template:
system rules, ranked context wrapped in delimited <source id="S#" doc=
"..." page="..."> tags, condensed conversation history wrapped in a
<history> tag (Module 7 - same structural-separation treatment as
sources, since history text ultimately originates from a prior user
turn and must be treated as data, never instructions), and the user
question delimited last as <question> (anti-injection defense layer 2
of Section 11.1's five).

Uses string.Template ($placeholder substitution), not f-strings/
.format(): source text or the user's question could contain literal
`{`/`}` characters that would corrupt .format()-style substitution;
`$name` has no such collision.

Templates load once at process startup (init_prompt_templates(), called
from app.main's lifespan) - a missing/unreadable template fails at
boot, not on the first /chat request. Mirrors the exact same
process-wide-singleton pattern as init_embedder()/get_embedder().
"""

import string
from dataclasses import dataclass
from pathlib import Path

from app.core.config import Settings
from app.core.constants import NOT_FOUND_TOKEN
from app.rag.ranking import RankedBlock
from app.utils.tokens import approx_token_count

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
_ANSWER_TEMPLATE_NAME = "answer_v1.txt"

_answer_template: string.Template | None = None


@dataclass(frozen=True)
class BuiltPrompt:
    text: str
    blocks: list[RankedBlock]
    prompt_tokens_estimate: int


def init_prompt_templates() -> None:
    """Load and cache all prompt templates. Called once from the app
    lifespan; raises (fails boot) if a template is missing or unreadable."""
    global _answer_template
    path = _PROMPTS_DIR / _ANSWER_TEMPLATE_NAME
    _answer_template = string.Template(path.read_text(encoding="utf-8"))


def get_answer_template() -> string.Template:
    if _answer_template is None:
        init_prompt_templates()
    assert _answer_template is not None
    return _answer_template


def _page_attr(block: RankedBlock) -> str:
    if block.page_start == block.page_end:
        return str(block.page_start)
    return f"{block.page_start}-{block.page_end}"


def _format_sources(blocks: list[RankedBlock]) -> str:
    parts = []
    for index, block in enumerate(blocks, start=1):
        parts.append(
            f'<source id="S{index}" doc="{block.document_name}" page="{_page_attr(block)}">\n'
            f"{block.text}\n"
            f"</source>"
        )
    return "\n\n".join(parts)


def _format_history_block(history: str) -> str:
    if not history:
        return ""
    return f"<history>\n{history}\n</history>"


def _assemble(question: str, blocks: list[RankedBlock], history: str) -> str:
    return get_answer_template().substitute(
        not_found_token=NOT_FOUND_TOKEN,
        sources=_format_sources(blocks),
        history=_format_history_block(history),
        question=f"<question>\n{question}\n</question>",
    )


def build_prompt(
    question: str, blocks: list[RankedBlock], *, history: str = "", settings: Settings
) -> BuiltPrompt:
    """blocks must already be sorted by score descending (ranking's
    contract) - dropping "the lowest-ranked block" here means dropping
    from the end. Once only one block remains and the budget is still
    exceeded, history is dropped next (SDD 6.3.5: "drop the lowest-ranked
    block, then trim history summary") before finally giving up and
    returning the oversized prompt as-is - sources always win over history,
    since a grounded answer needs its context more than its memory."""
    remaining = list(blocks)
    remaining_history = history
    while True:
        text = _assemble(question, remaining, remaining_history)
        token_estimate = approx_token_count(text)
        if token_estimate <= settings.prompt_token_budget:
            return BuiltPrompt(text=text, blocks=remaining, prompt_tokens_estimate=token_estimate)
        if len(remaining) > 1:
            remaining = remaining[:-1]
        elif remaining_history:
            remaining_history = ""
        else:
            return BuiltPrompt(text=text, blocks=remaining, prompt_tokens_estimate=token_estimate)
