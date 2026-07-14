"""Unit tests for app/rag/chunker.py (SDD Section 7.2 Stage 3).

Works against synthetic PageText/HeadingMarker objects (no PyMuPDF
needed) so section boundaries, overlap, and page offsets can be
constructed with exact, known values.
"""

import pytest

from app.rag.chunker import chunk_pages
from app.rag.pdf_processor import HeadingMarker, PageText

# Chunking now calls the real BGE tokenizer (app/utils/tokens.py) for
# token counts, so this file transitively touches the real HF asset.
pytestmark = pytest.mark.model


def _page(
    page_number: int, text: str, headings: list[HeadingMarker] | None = None
) -> PageText:
    return PageText(
        page_number=page_number,
        text=text,
        is_empty=not text.strip(),
        is_low_text=False,
        headings=headings or [],
    )


def test_large_section_is_packed_into_multiple_chunks_near_target_size():
    paragraphs = [f"Paragraph {i} " + " ".join(["word"] * 20) for i in range(20)]
    text = "\n\n".join(paragraphs)
    page = _page(1, text)

    chunks = chunk_pages([page], target_tokens=100, overlap_tokens=20)

    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    # Overlap inflates a chunk by at most ~one unit past the target; a
    # generous multiple keeps this a "no runaway chunk" check, not exact.
    assert all(c.token_count <= 100 * 2 for c in chunks)
    assert chunks[0].char_start == 0
    assert chunks[-1].char_end == len(text)


def test_overlap_carries_tail_of_previous_chunk_into_next():
    # Word counts sized with a wide margin over target_tokens: the real
    # BGE tokenizer counts short repeated words more efficiently than the
    # old word-based approximation (~1.3 tokens/word), so each paragraph
    # alone must still clear the target comfortably while the combined
    # text overflows it.
    paragraph_a = "Intro words " + " ".join(["alpha"] * 60) + " ALPHA_END"
    paragraph_b = "BETA_MARKER " + " ".join(["beta"] * 60)
    text = f"{paragraph_a}\n\n{paragraph_b}"
    page = _page(1, text)

    chunks = chunk_pages([page], target_tokens=80, overlap_tokens=30)

    assert len(chunks) == 2
    assert "ALPHA_END" in chunks[0].text
    assert "BETA_MARKER" not in chunks[0].text
    # Overlap: the tail of chunk 1 reappears at the start of chunk 2.
    assert "ALPHA_END" in chunks[1].text
    assert "BETA_MARKER" in chunks[1].text


def test_chunks_never_cross_a_section_boundary():
    section_one = "Section One\n\nContent about leave ALPHA_MARKER for employees."
    section_two = "Section Two\n\nContent about notice BETA_MARKER for employees."
    text = f"{section_one}\n\n{section_two}"
    headings = [
        HeadingMarker(offset=0, title="Section One"),
        HeadingMarker(offset=text.index("Section Two"), title="Section Two"),
    ]
    page = _page(1, text, headings=headings)

    chunks = chunk_pages([page], target_tokens=1000, overlap_tokens=50)

    assert len(chunks) == 2
    first, second = chunks
    assert first.section_title == "Section One"
    assert "ALPHA_MARKER" in first.text
    assert "BETA_MARKER" not in first.text
    assert second.section_title == "Section Two"
    assert "BETA_MARKER" in second.text
    assert "ALPHA_MARKER" not in second.text


def test_oversized_single_paragraph_is_hard_split_on_words():
    words = [f"word{i}" for i in range(300)]
    text = " ".join(words)  # no punctuation/blank lines -> one giant "sentence"
    page = _page(1, text)

    chunks = chunk_pages([page], target_tokens=50, overlap_tokens=10)

    assert len(chunks) > 1
    assert chunks[0].text.startswith("word0")
    assert chunks[-1].text.endswith("word299")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_page_start_end_reflects_pages_a_chunk_actually_spans():
    pages = [
        _page(1, "First page content about onboarding."),
        _page(2, "Second page content about benefits."),
        _page(3, "Third page content about offboarding."),
    ]

    spanning_chunks = chunk_pages(pages, target_tokens=1000, overlap_tokens=10)
    assert len(spanning_chunks) == 1
    assert spanning_chunks[0].page_start == 1
    assert spanning_chunks[0].page_end == 3

    single_page_chunks = chunk_pages([pages[1]], target_tokens=1000, overlap_tokens=10)
    assert len(single_page_chunks) == 1
    assert single_page_chunks[0].page_start == 2
    assert single_page_chunks[0].page_end == 2


def test_empty_pages_are_excluded_from_chunking():
    pages = [
        _page(1, "Real content on page one."),
        _page(2, ""),
        _page(3, "Real content on page three."),
    ]

    chunks = chunk_pages(pages, target_tokens=1000, overlap_tokens=10)

    assert len(chunks) == 1
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 3


def test_no_pages_returns_no_chunks():
    assert chunk_pages([], target_tokens=600, overlap_tokens=100) == []
