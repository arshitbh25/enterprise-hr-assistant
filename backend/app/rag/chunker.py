"""Structure-aware recursive chunking (SDD Section 7.2 Stage 3).

Rationale for the approach and the 600/100 token numbers is written up
in docs/chunking-decision.md. Summary: sections are cut at detected
heading offsets first (falling back to a single implicit section when
no headings were found); within a section, text is packed greedily up
to ~600 tokens with ~100-token overlap, recursing into
paragraph -> sentence -> word splitting only when a unit doesn't fit the
target on its own. Chunks never cross a section boundary, and a
section's final chunk is flushed regardless of size.

Everything here operates on integer (start, end) offsets into one
concatenated `global_text` string rather than passing substrings around,
so char_start/char_end on the resulting chunks are exact and cheap to
compute.
"""

import re
from dataclasses import dataclass

from app.rag.pdf_processor import PageText
from app.utils.tokens import approx_token_count

_PAGE_SEPARATOR = "\n\n"
_APPROX_TOKENS_PER_WORD = 1.3

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class RawChunk:
    text: str
    char_start: int
    char_end: int
    page_start: int
    page_end: int
    section_title: str | None
    chunk_index: int
    token_count: int


def _non_delimiter_spans(
    text: str, start: int, end: int, pattern: re.Pattern[str]
) -> list[tuple[int, int]]:
    """Spans of text[start:end] that fall *between* pattern matches."""
    spans: list[tuple[int, int]] = []
    last_end = start
    for match in pattern.finditer(text, start, end):
        if match.start() > last_end:
            spans.append((last_end, match.start()))
        last_end = match.end()
    if last_end < end:
        spans.append((last_end, end))
    return spans


def _strip_span(text: str, start: int, end: int) -> tuple[int, int]:
    substring = text[start:end]
    left_trim = len(substring) - len(substring.lstrip())
    right_trim = len(substring) - len(substring.rstrip())
    return start + left_trim, end - right_trim


def _units_from_words(
    text: str, start: int, end: int, target_tokens: int
) -> list[tuple[int, int]]:
    words = _non_delimiter_spans(text, start, end, _WHITESPACE_RE)
    if not words:
        return []
    max_words_per_unit = max(1, int(target_tokens / _APPROX_TOKENS_PER_WORD))
    return [
        (words[i][0], words[min(i + max_words_per_unit, len(words)) - 1][1])
        for i in range(0, len(words), max_words_per_unit)
    ]


def _units_from_sentences(
    text: str, start: int, end: int, target_tokens: int
) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for s_start, s_end in _non_delimiter_spans(text, start, end, _SENTENCE_RE):
        s_start, s_end = _strip_span(text, s_start, s_end)
        if s_start >= s_end:
            continue
        if approx_token_count(text[s_start:s_end]) <= target_tokens:
            units.append((s_start, s_end))
        else:
            units.extend(_units_from_words(text, s_start, s_end, target_tokens))
    return units


def _units_from_paragraphs(
    text: str, start: int, end: int, target_tokens: int
) -> list[tuple[int, int]]:
    units: list[tuple[int, int]] = []
    for p_start, p_end in _non_delimiter_spans(text, start, end, _PARAGRAPH_RE):
        p_start, p_end = _strip_span(text, p_start, p_end)
        if p_start >= p_end:
            continue
        if approx_token_count(text[p_start:p_end]) <= target_tokens:
            units.append((p_start, p_end))
        else:
            units.extend(_units_from_sentences(text, p_start, p_end, target_tokens))
    return units


def _build_sections(
    text_length: int, headings: list[tuple[int, str]]
) -> list[tuple[int, int, str | None]]:
    if not headings:
        return [(0, text_length, None)]

    sorted_headings = sorted(headings, key=lambda h: h[0])
    sections: list[tuple[int, int, str | None]] = []
    if sorted_headings[0][0] > 0:
        sections.append((0, sorted_headings[0][0], None))
    for index, (offset, title) in enumerate(sorted_headings):
        end = sorted_headings[index + 1][0] if index + 1 < len(sorted_headings) else text_length
        sections.append((offset, end, title))
    return sections


def _resolve_page_range(
    start: int, end: int, page_offsets: list[tuple[int, int, int]]
) -> tuple[int, int]:
    matching = [
        page_number
        for page_number, p_start, p_end in page_offsets
        if p_start < end and p_end > start
    ]
    if not matching:
        matching = [page_offsets[0][0]]
    return min(matching), max(matching)


def _finalize_chunk(
    text: str,
    start: int,
    end: int,
    *,
    page_offsets: list[tuple[int, int, int]],
    section_title: str | None,
    chunk_index: int,
) -> RawChunk:
    page_start, page_end = _resolve_page_range(start, end, page_offsets)
    chunk_text = text[start:end]
    return RawChunk(
        text=chunk_text,
        char_start=start,
        char_end=end,
        page_start=page_start,
        page_end=page_end,
        section_title=section_title,
        chunk_index=chunk_index,
        token_count=approx_token_count(chunk_text),
    )


def _overlap_start(text: str, start: int, end: int, overlap_tokens: int) -> int:
    """Offset within [start, end) marking the start of the trailing
    ~overlap_tokens words, used to seed the next chunk in the same section."""
    if overlap_tokens <= 0:
        return end
    words = _non_delimiter_spans(text, start, end, _WHITESPACE_RE)
    if not words:
        return end
    overlap_word_count = max(1, int(overlap_tokens / _APPROX_TOKENS_PER_WORD))
    return words[max(0, len(words) - overlap_word_count)][0]


def _pack_units(
    text: str,
    units: list[tuple[int, int]],
    *,
    target_tokens: int,
    overlap_tokens: int,
    page_offsets: list[tuple[int, int, int]],
    section_title: str | None,
    next_index: int,
) -> tuple[list[RawChunk], int]:
    if not units:
        return [], next_index

    chunks: list[RawChunk] = []
    buffer_start, buffer_end = units[0]
    for _unit_start, unit_end in units[1:]:
        if approx_token_count(text[buffer_start:unit_end]) > target_tokens:
            chunks.append(
                _finalize_chunk(
                    text,
                    buffer_start,
                    buffer_end,
                    page_offsets=page_offsets,
                    section_title=section_title,
                    chunk_index=next_index,
                )
            )
            next_index += 1
            buffer_start = _overlap_start(text, buffer_start, buffer_end, overlap_tokens)
            buffer_end = unit_end
        else:
            buffer_end = unit_end

    chunks.append(
        _finalize_chunk(
            text,
            buffer_start,
            buffer_end,
            page_offsets=page_offsets,
            section_title=section_title,
            chunk_index=next_index,
        )
    )
    next_index += 1
    return chunks, next_index


def chunk_pages(
    pages: list[PageText], *, target_tokens: int, overlap_tokens: int
) -> list[RawChunk]:
    included_pages = [page for page in pages if not page.is_empty]
    if not included_pages:
        return []

    text_parts: list[str] = []
    page_offsets: list[tuple[int, int, int]] = []
    headings: list[tuple[int, str]] = []
    cursor = 0
    for page in included_pages:
        start = cursor
        text_parts.append(page.text)
        cursor += len(page.text)
        page_offsets.append((page.page_number, start, cursor))
        for heading in page.headings:
            headings.append((start + heading.offset, heading.title))
        text_parts.append(_PAGE_SEPARATOR)
        cursor += len(_PAGE_SEPARATOR)
    global_text = "".join(text_parts)

    all_chunks: list[RawChunk] = []
    next_index = 0
    for section_start, section_end, section_title in _build_sections(len(global_text), headings):
        if section_start >= section_end:
            continue
        units = _units_from_paragraphs(global_text, section_start, section_end, target_tokens)
        if not units:
            continue
        chunks, next_index = _pack_units(
            global_text,
            units,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            page_offsets=page_offsets,
            section_title=section_title,
            next_index=next_index,
        )
        all_chunks.extend(chunks)

    return all_chunks
