"""Unit tests for app/rag/citations.py (SDD Section 6.3.8, 7.2 Stage 12-13)."""

import uuid

from app.core.config import Settings
from app.core.constants import NOT_FOUND_TOKEN, ConfidenceLevel
from app.rag.citations import process_answer
from app.rag.ranking import RankedBlock


def _block(**overrides) -> RankedBlock:
    defaults = dict(
        document_id=uuid.uuid4(),
        document_name="Leave_Policy.pdf",
        page_start=12,
        page_end=12,
        section_title="Casual Leave",
        text="Employees receive twelve days of casual leave per year.",
        score=0.9,
        token_count=10,
        source_chunk_ids=[uuid.uuid4()],
    )
    defaults.update(overrides)
    return RankedBlock(**defaults)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_not_found_token_returns_not_found_result():
    result = process_answer(NOT_FOUND_TOKEN, [_block()], settings=_settings())

    assert result.not_found is True
    assert result.citations == []
    assert result.confidence == ConfidenceLevel.NOT_FOUND
    assert result.answer_text == ""


def test_not_found_token_with_surrounding_whitespace_still_matches():
    result = process_answer(f"  {NOT_FOUND_TOKEN}\n", [_block()], settings=_settings())

    assert result.not_found is True


def test_valid_single_citation_is_high_confidence_above_threshold():
    block = _block(score=0.9)

    result = process_answer(
        "Employees get twelve days of leave. [S1]",
        [block],
        settings=_settings(retrieval_high_confidence_threshold=0.5),
    )

    assert result.not_found is False
    assert result.confidence == ConfidenceLevel.HIGH
    [citation] = result.citations
    assert citation.document_name == "Leave_Policy.pdf"
    assert citation.page_start == 12
    assert citation.section_title == "Casual Leave"


def test_valid_citation_is_low_confidence_below_high_threshold():
    block = _block(score=0.4)

    result = process_answer(
        "Employees get twelve days of leave. [S1]",
        [block],
        settings=_settings(retrieval_high_confidence_threshold=0.5),
    )

    assert result.not_found is False
    assert result.confidence == ConfidenceLevel.LOW


def test_multiple_citations_ordered_by_first_appearance_and_deduped():
    first = _block(document_name="A.pdf", score=0.9)
    second = _block(document_name="B.pdf", score=0.8)

    result = process_answer(
        "Claim one. [S2] Claim two, repeated reference. [S1] [S2]",
        [first, second],
        settings=_settings(),
    )

    assert [c.document_name for c in result.citations] == ["B.pdf", "A.pdf"]


def test_tags_are_stripped_from_the_final_prose():
    result = process_answer(
        "Employees get twelve days of leave. [S1]", [_block()], settings=_settings()
    )

    assert "[S1]" not in result.answer_text
    assert "Employees get twelve days of leave." in result.answer_text


def test_invalid_tag_reference_downgrades_to_not_found():
    result = process_answer(
        "Employees get twelve days of leave. [S2]", [_block()], settings=_settings()
    )

    assert result.not_found is True
    assert result.citations == []


def test_zero_tags_on_non_refusal_answer_downgrades_to_not_found():
    result = process_answer(
        "Employees get twelve days of leave with no citation at all.",
        [_block()],
        settings=_settings(),
    )

    assert result.not_found is True


def test_snippet_is_truncated_for_long_block_text():
    long_text = "word " * 100
    block = _block(text=long_text)

    result = process_answer("Answer. [S1]", [block], settings=_settings())

    [citation] = result.citations
    assert len(citation.snippet) <= 243  # 240 + "..."
    assert citation.snippet.endswith("...")


def test_representative_chunk_id_is_the_first_source_chunk_id():
    chunk_a, chunk_b = uuid.uuid4(), uuid.uuid4()
    block = _block(source_chunk_ids=[chunk_a, chunk_b])

    result = process_answer("Answer. [S1]", [block], settings=_settings())

    [citation] = result.citations
    assert citation.chunk_id == chunk_a
