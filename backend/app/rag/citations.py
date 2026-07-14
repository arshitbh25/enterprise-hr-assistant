"""Citation resolution + lightweight format-compliance gate (SDD Section
6.3.8, Section 7.2 Stage 12-13).

Resolves [S#] tags in the model's draft answer back to user-facing
citations, and doubles as a simplified stand-in for part of the full
Response Validation Agent's job (SDD 6.3.7), which is Phase 6 scope:
format compliance (do the tags actually exist?) and refusal
normalization (did the model emit the exact NOT_FOUND token?) both
belong here per the user's explicit Phase-5 instruction, since there's
no separate validator agent yet to do finer-grained repair. The full
groundedness/leak-check heuristics remain Phase 6.

Per that instruction, ANY citation-integrity problem - a tag referencing
a source number that doesn't exist, or zero tags on a non-refusal
answer - downgrades the *whole* answer to NOT_FOUND (fail closed), not
just the offending claim. This is stricter than SDD 6.3.8's original
"drop just that claim's tag" language, a deliberate simplification for
this phase.
"""

import re
import uuid
from dataclasses import dataclass

from app.core.config import Settings
from app.core.constants import NOT_FOUND_TOKEN, ConfidenceLevel
from app.core.logging import get_logger
from app.rag.ranking import RankedBlock

logger = get_logger(__name__)

_TAG_RE = re.compile(r"\[S(\d+)\]")
_SNIPPET_MAX_CHARS = 240


@dataclass(frozen=True)
class Citation:
    chunk_id: uuid.UUID  # representative constituent chunk, for persistence only
    document_name: str
    page_start: int
    page_end: int
    section_title: str | None
    snippet: str


@dataclass(frozen=True)
class CitationResult:
    not_found: bool
    answer_text: str
    citations: list[Citation]
    confidence: ConfidenceLevel


def _not_found_result() -> CitationResult:
    return CitationResult(
        not_found=True, answer_text="", citations=[], confidence=ConfidenceLevel.NOT_FOUND
    )


def _ordered_unique_tag_indices(draft_answer: str) -> list[int]:
    seen: list[int] = []
    for match in _TAG_RE.finditer(draft_answer):
        index = int(match.group(1))
        if index not in seen:
            seen.append(index)
    return seen


def _strip_tags(draft_answer: str) -> str:
    stripped = _TAG_RE.sub("", draft_answer)
    return re.sub(r"[ \t]+", " ", stripped).strip()


def _snippet_from(text: str) -> str:
    if len(text) <= _SNIPPET_MAX_CHARS:
        return text
    return text[:_SNIPPET_MAX_CHARS].rstrip() + "..."


def _to_citation(block: RankedBlock) -> Citation:
    representative_chunk_id = block.source_chunk_ids[0]
    return Citation(
        chunk_id=representative_chunk_id,
        document_name=block.document_name,
        page_start=block.page_start,
        page_end=block.page_end,
        section_title=block.section_title,
        snippet=_snippet_from(block.text),
    )


def _compute_confidence(cited_blocks: list[RankedBlock], settings: Settings) -> ConfidenceLevel:
    top_score = max(block.score for block in cited_blocks)
    if top_score >= settings.retrieval_high_confidence_threshold:
        return ConfidenceLevel.HIGH
    return ConfidenceLevel.LOW


def process_answer(
    draft_answer: str, blocks: list[RankedBlock], *, settings: Settings
) -> CitationResult:
    if draft_answer.strip() == NOT_FOUND_TOKEN:
        return _not_found_result()

    cited_indices = _ordered_unique_tag_indices(draft_answer)
    invalid = [index for index in cited_indices if index < 1 or index > len(blocks)]
    if not cited_indices or invalid:
        logger.warning(
            "citation_validation_failed",
            reason="no_citations" if not cited_indices else "invalid_tag_reference",
            cited_indices=cited_indices,
            invalid_indices=invalid,
            available_blocks=len(blocks),
        )
        return _not_found_result()

    cited_blocks = [blocks[index - 1] for index in cited_indices]
    return CitationResult(
        not_found=False,
        answer_text=_strip_tags(draft_answer),
        citations=[_to_citation(block) for block in cited_blocks],
        confidence=_compute_confidence(cited_blocks, settings),
    )
