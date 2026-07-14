"""Context Ranking Agent (SDD Section 6.3.4, Section 7.2 Stage 8).

Quality gate on retrieval: threshold filter (anti-hallucination gate
#1 - weak context never reaches the LLM), near-duplicate removal, MMR
diversity selection, adjacent-chunk merging, and a token-budget cap.
An empty return list is the NOT_FOUND signal the caller (/chat) acts on.

Near-duplicate and MMR-diversity similarity both use a cheap word-set
Jaccard proxy rather than pairwise embedding math - no extra encoding
work, and "how much text do two chunks share" is exactly what these two
steps need to know.
"""

import uuid
from dataclasses import dataclass, field

from app.core.config import Settings
from app.rag.retriever import RetrievedChunk
from app.utils.tokens import approx_token_count

_NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.8


@dataclass(frozen=True)
class RankedBlock:
    document_id: uuid.UUID
    document_name: str
    page_start: int
    page_end: int
    section_title: str | None
    text: str
    score: float
    token_count: int
    # Every original chunk that contributed to this block, ordered by
    # score descending - source_chunk_ids[0] is the representative used
    # by Module 5 when persisting a citation for a merged block (the
    # message_citations schema has one chunk_id FK per citation, which
    # predates ranking's ability to merge several chunks into one block).
    source_chunk_ids: list[uuid.UUID] = field(default_factory=list)


def _word_set(text: str) -> frozenset[str]:
    return frozenset(text.lower().split())


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union else 0.0


def _threshold_filter(
    chunks: list[RetrievedChunk], threshold: float
) -> list[RetrievedChunk]:
    survivors = [chunk for chunk in chunks if chunk.score >= threshold]
    return sorted(survivors, key=lambda chunk: chunk.score, reverse=True)


def _remove_near_duplicates(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """chunks must already be sorted by score descending - a later
    (lower-scored) near-duplicate of an already-kept chunk is dropped."""
    kept: list[RetrievedChunk] = []
    kept_word_sets: list[frozenset[str]] = []
    for chunk in chunks:
        words = _word_set(chunk.text)
        if any(_jaccard(words, kept_words) >= _NEAR_DUPLICATE_JACCARD_THRESHOLD
               for kept_words in kept_word_sets):
            continue
        kept.append(chunk)
        kept_word_sets.append(words)
    return kept


def _mmr_select(
    chunks: list[RetrievedChunk], *, lambda_: float, max_blocks: int
) -> list[RetrievedChunk]:
    """chunks must already be sorted by score descending."""
    remaining = list(chunks)
    selected: list[RetrievedChunk] = []
    selected_word_sets: list[frozenset[str]] = []

    while remaining and len(selected) < max_blocks:
        if not selected:
            best = remaining[0]
        else:
            def _mmr_value(candidate: RetrievedChunk) -> float:
                candidate_words = _word_set(candidate.text)
                max_similarity = max(
                    (_jaccard(candidate_words, words) for words in selected_word_sets),
                    default=0.0,
                )
                return lambda_ * candidate.score - (1 - lambda_) * max_similarity

            best = max(remaining, key=_mmr_value)

        selected.append(best)
        selected_word_sets.append(_word_set(best.text))
        remaining.remove(best)

    return selected


def _pages_touch_or_overlap(a: RetrievedChunk, b: RetrievedChunk) -> bool:
    return b.page_start <= a.page_end + 1


def _merge_adjacent(chunks: list[RetrievedChunk]) -> list[RankedBlock]:
    groups: dict[tuple[uuid.UUID, str | None], list[RetrievedChunk]] = {}
    for chunk in chunks:
        groups.setdefault((chunk.document_id, chunk.section_title), []).append(chunk)

    blocks: list[RankedBlock] = []
    for (document_id, section_title), group in groups.items():
        group_by_page = sorted(group, key=lambda c: c.page_start)
        current: list[RetrievedChunk] = [group_by_page[0]]
        for chunk in group_by_page[1:]:
            if _pages_touch_or_overlap(current[-1], chunk):
                current.append(chunk)
            else:
                blocks.append(_build_block(document_id, section_title, current))
                current = [chunk]
        blocks.append(_build_block(document_id, section_title, current))

    return sorted(blocks, key=lambda block: block.score, reverse=True)


def _build_block(
    document_id: uuid.UUID, section_title: str | None, constituents: list[RetrievedChunk]
) -> RankedBlock:
    text = "\n\n".join(c.text for c in constituents)
    by_score_desc = sorted(constituents, key=lambda c: c.score, reverse=True)
    return RankedBlock(
        document_id=document_id,
        document_name=constituents[0].document_name,
        page_start=min(c.page_start for c in constituents),
        page_end=max(c.page_end for c in constituents),
        section_title=section_title,
        text=text,
        score=max(c.score for c in constituents),
        token_count=approx_token_count(text),
        source_chunk_ids=[c.chunk_id for c in by_score_desc],
    )


def _cap_token_budget(blocks: list[RankedBlock], budget: int) -> list[RankedBlock]:
    """blocks must already be sorted by score descending. Always keeps at
    least the top block, even if it alone exceeds the budget."""
    if not blocks:
        return []
    kept = [blocks[0]]
    total = blocks[0].token_count
    for block in blocks[1:]:
        if total + block.token_count > budget:
            break
        kept.append(block)
        total += block.token_count
    return kept


def rank_chunks(chunks: list[RetrievedChunk], *, settings: Settings) -> list[RankedBlock]:
    survivors = _threshold_filter(chunks, settings.retrieval_similarity_threshold)
    if not survivors:
        return []

    deduped = _remove_near_duplicates(survivors)
    selected = _mmr_select(
        deduped, lambda_=settings.mmr_lambda, max_blocks=settings.context_max_blocks
    )
    merged = _merge_adjacent(selected)
    return _cap_token_budget(merged, settings.context_token_budget)
