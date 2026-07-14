"""Unit tests for app/rag/ranking.py (SDD Section 6.3.4, 7.2 Stage 8).

Uses synthetic RetrievedChunk objects (no embedder/Chroma needed) - only
approx_token_count (the real BGE tokenizer, Phase 4) is a real
dependency here, hence the `model` marker.
"""

import uuid

import pytest

from app.core.config import Settings
from app.rag import ranking
from app.rag.ranking import rank_chunks
from app.rag.retriever import RetrievedChunk

pytestmark = pytest.mark.model


def _chunk(**overrides) -> RetrievedChunk:
    defaults = dict(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_name="Leave_Policy.pdf",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        text="Employees receive twelve days of annual leave per year.",
        score=0.9,
    )
    defaults.update(overrides)
    return RetrievedChunk(**defaults)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_threshold_filter_removes_low_scores_and_sorts_descending():
    chunks = [_chunk(score=0.5), _chunk(score=0.2), _chunk(score=0.4)]

    survivors = ranking._threshold_filter(chunks, 0.35)

    assert [c.score for c in survivors] == [0.5, 0.4]


def test_remove_near_duplicates_keeps_the_higher_scored_copy():
    high = _chunk(score=0.9, text="Employees receive twelve days of annual leave per year.")
    low_duplicate = _chunk(
        score=0.6, text="Employees receive twelve days of annual leave per year."
    )

    kept = ranking._remove_near_duplicates([high, low_duplicate])

    assert kept == [high]


def test_mmr_select_prefers_diverse_chunk_over_similar_higher_scored_one():
    chunk_a = _chunk(score=0.9, text="alpha alpha alpha unique_a", section_title="A")
    chunk_b = _chunk(
        score=0.85, text="alpha alpha alpha unique_a variant", section_title="B"
    )
    chunk_c = _chunk(score=0.7, text="beta beta beta unique_c", section_title="C")

    selected = ranking._mmr_select([chunk_a, chunk_b, chunk_c], lambda_=0.5, max_blocks=2)

    assert selected == [chunk_a, chunk_c]


def test_merge_adjacent_same_document_and_section_contiguous_pages():
    document_id = uuid.uuid4()
    first = _chunk(document_id=document_id, section_title="Leave", page_start=1, page_end=1,
                    text="Part one.", score=0.8)
    second = _chunk(document_id=document_id, section_title="Leave", page_start=2, page_end=2,
                     text="Part two.", score=0.6)

    [block] = ranking._merge_adjacent([first, second])

    assert block.page_start == 1
    assert block.page_end == 2
    assert block.text == "Part one.\n\nPart two."
    assert block.score == 0.8
    assert block.source_chunk_ids == [first.chunk_id, second.chunk_id]


def test_merge_adjacent_non_contiguous_pages_stay_separate():
    document_id = uuid.uuid4()
    first = _chunk(document_id=document_id, section_title="Leave", page_start=1, page_end=1)
    second = _chunk(document_id=document_id, section_title="Leave", page_start=5, page_end=5)

    blocks = ranking._merge_adjacent([first, second])

    assert len(blocks) == 2


def test_merge_adjacent_different_sections_stay_separate_even_with_touching_pages():
    document_id = uuid.uuid4()
    first = _chunk(document_id=document_id, section_title="Section A", page_start=1, page_end=1)
    second = _chunk(document_id=document_id, section_title="Section B", page_start=2, page_end=2)

    blocks = ranking._merge_adjacent([first, second])

    assert len(blocks) == 2


def test_cap_token_budget_drops_lowest_scored_block_when_over_budget():
    blocks = [
        ranking.RankedBlock(
            document_id=uuid.uuid4(), document_name="d.pdf", page_start=1, page_end=1,
            section_title=None, text="x", score=score, token_count=800, source_chunk_ids=[],
        )
        for score in (0.9, 0.8, 0.7)
    ]

    kept = ranking._cap_token_budget(blocks, budget=2000)

    assert [b.score for b in kept] == [0.9, 0.8]


def test_cap_token_budget_always_keeps_top_block_even_if_oversized():
    oversized = ranking.RankedBlock(
        document_id=uuid.uuid4(), document_name="d.pdf", page_start=1, page_end=1,
        section_title=None, text="x", score=0.9, token_count=5000, source_chunk_ids=[],
    )

    kept = ranking._cap_token_budget([oversized], budget=2000)

    assert kept == [oversized]


def test_rank_chunks_returns_empty_when_nothing_clears_threshold():
    chunks = [_chunk(score=0.1), _chunk(score=0.2)]

    assert rank_chunks(chunks, settings=_settings()) == []


def test_rank_chunks_end_to_end_happy_path():
    chunk_a = _chunk(score=0.9, section_title="Leave Policy", text="Leave policy content here.")
    chunk_b = _chunk(
        score=0.6,
        document_id=uuid.uuid4(),
        section_title="Dress Code",
        text="Dress code content here.",
    )

    blocks = rank_chunks([chunk_a, chunk_b], settings=_settings())

    assert len(blocks) == 2
    assert blocks[0].score >= blocks[1].score
    assert all(b.token_count > 0 for b in blocks)
