"""PDF text extraction and cleaning (SDD Section 7.2 Stage 2, Section 11.4).

Uses PyMuPDF's text-only extraction APIs — no JavaScript execution, no
embedded-file extraction, no external link following (Section 11.4).
Headings are detected heuristically from font-size/bold span metadata;
this is intentionally a heuristic, not a layout parser, and degrades
gracefully to "no headings found" (see docs/chunking-decision.md).

Timeout + memory guard (Section 11.4) is best-effort, not a hard OS
sandbox: a page-count cap rejects decompression-bomb-style page counts
before any text is extracted, and the extraction pass runs inside a
thread with a wall-clock timeout so a pathological PDF can't hang the
ingestion pipeline indefinitely. PyMuPDF's native code isn't preemptible,
so a timed-out extraction thread may keep running in the background;
true process-level sandboxing is out of scope for this phase.
"""

import re
import unicodedata
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field

import fitz

from app.core.exceptions import CorruptPdfError, PdfProcessingTimeoutError, PdfTooManyPagesError
from app.core.logging import get_logger

logger = get_logger(__name__)

_BOLD_FLAG = 1 << 4
_HEADING_SIZE_RATIO = 1.15
_HEADING_MAX_CHARS = 120
_MIN_PAGES_FOR_HEADER_FOOTER_DETECTION = 3
_HEADER_FOOTER_FREQUENCY_THRESHOLD = 0.5

_DIGIT_RUN_RE = re.compile(r"\d+")
_HYPHEN_BREAK_RE = re.compile(r"([A-Za-z])-\n([a-z])")
_MULTI_SPACE_RE = re.compile(r"[ \t]+")
_MULTI_BLANK_LINE_RE = re.compile(r"\n{3,}")
_BULLET_RE = re.compile(r"[•●▪‣]")


@dataclass(frozen=True)
class HeadingMarker:
    offset: int
    title: str


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-indexed, matches the original PDF for citations
    text: str
    is_empty: bool
    is_low_text: bool
    headings: list[HeadingMarker] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionResult:
    pages: list[PageText]
    page_count: int


@dataclass
class _RawLine:
    text: str
    is_heading_candidate: bool
    is_paragraph_break: bool = False


@dataclass
class _RawPage:
    lines: list[_RawLine]
    has_images: bool


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _BULLET_RE.sub("-", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _MULTI_BLANK_LINE_RE.sub("\n\n", text)
    return text.strip()


def _repair_hyphenation(text: str) -> str:
    return _HYPHEN_BREAK_RE.sub(r"\1\2", text)


def _line_normalized_key(line: str) -> str:
    """Normalized form used to detect repeated headers/footers across
    pages: digits collapsed so page numbers ('Page 3 of 40') still match."""
    key = unicodedata.normalize("NFKC", line).strip().lower()
    return _DIGIT_RUN_RE.sub("#", key)


def _collect_font_size_mode(page_dicts: list[dict]) -> float:
    sizes: Counter[float] = Counter()
    for page_dict in page_dicts:
        for block in page_dict.get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if text:
                        sizes[round(span["size"], 1)] += len(text)
    if not sizes:
        return 0.0
    return sizes.most_common(1)[0][0]


def _build_raw_page(page_dict: dict, body_font_size: float, has_images: bool) -> _RawPage:
    lines: list[_RawLine] = []
    for block_index, block in enumerate(page_dict.get("blocks", [])):
        block_lines = block.get("lines", [])
        if block_index > 0 and block_lines:
            lines.append(_RawLine(text="", is_heading_candidate=False, is_paragraph_break=True))
        for line in block_lines:
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(span.get("text", "") for span in spans).strip()
            if not text:
                continue
            first_span = spans[0]
            is_heading = (
                len(text) <= _HEADING_MAX_CHARS
                and body_font_size > 0
                and (
                    first_span.get("size", 0) >= body_font_size * _HEADING_SIZE_RATIO
                    or bool(first_span.get("flags", 0) & _BOLD_FLAG)
                )
                and first_span.get("size", 0) >= body_font_size
            )
            lines.append(_RawLine(text=text, is_heading_candidate=is_heading))
    return _RawPage(lines=lines, has_images=has_images)


def _strip_header_footer_lines(raw_pages: list[_RawPage]) -> None:
    """Mutates raw_pages in place, blanking out first/last lines that
    repeat across a majority of pages (SDD Stage 2)."""
    if len(raw_pages) < _MIN_PAGES_FOR_HEADER_FOOTER_DETECTION:
        return

    def _content_lines(raw_page: _RawPage) -> list[_RawLine]:
        return [line for line in raw_page.lines if line.text]

    first_line_counts: Counter[str] = Counter()
    last_line_counts: Counter[str] = Counter()
    for raw_page in raw_pages:
        content = _content_lines(raw_page)
        if not content:
            continue
        first_line_counts[_line_normalized_key(content[0].text)] += 1
        last_line_counts[_line_normalized_key(content[-1].text)] += 1

    threshold = len(raw_pages) * _HEADER_FOOTER_FREQUENCY_THRESHOLD
    header_keys = {key for key, count in first_line_counts.items() if count > threshold}
    footer_keys = {key for key, count in last_line_counts.items() if count > threshold}

    for raw_page in raw_pages:
        content = _content_lines(raw_page)
        if not content:
            continue
        if _line_normalized_key(content[0].text) in header_keys:
            content[0].text = ""
            content[0].is_heading_candidate = False
        if len(content) > 1 and _line_normalized_key(content[-1].text) in footer_keys:
            content[-1].text = ""
            content[-1].is_heading_candidate = False


def _render_page_text(raw_page: _RawPage) -> tuple[str, list[HeadingMarker]]:
    heading_candidates = [line.text for line in raw_page.lines if line.is_heading_candidate]

    joined_lines = []
    for line in raw_page.lines:
        if line.is_paragraph_break:
            joined_lines.append("")
        elif line.text:
            joined_lines.append(line.text)
    raw_text = "\n".join(joined_lines)
    raw_text = _repair_hyphenation(raw_text)
    cleaned_text = _normalize_text(raw_text)

    headings: list[HeadingMarker] = []
    for candidate in heading_candidates:
        normalized_candidate = _normalize_text(candidate)
        if not normalized_candidate:
            continue
        offset = cleaned_text.find(normalized_candidate)
        if offset >= 0:
            headings.append(HeadingMarker(offset=offset, title=normalized_candidate))
    return cleaned_text, headings


def _extract_all_pages(
    doc: fitz.Document, *, min_extractable_chars_per_page: int
) -> ExtractionResult:
    page_dicts = [page.get_text("dict") for page in doc]
    has_images_per_page = [bool(page.get_images()) for page in doc]
    body_font_size = _collect_font_size_mode(page_dicts)

    raw_pages = [
        _build_raw_page(page_dict, body_font_size, has_images)
        for page_dict, has_images in zip(page_dicts, has_images_per_page, strict=True)
    ]
    _strip_header_footer_lines(raw_pages)

    pages: list[PageText] = []
    low_text_page_numbers: list[int] = []
    for index, raw_page in enumerate(raw_pages):
        page_number = index + 1
        text, headings = _render_page_text(raw_page)
        is_empty = not text
        is_low_text = (
            not is_empty
            and raw_page.has_images
            and len(text) < min_extractable_chars_per_page
        ) or (is_empty and raw_page.has_images)
        if is_low_text:
            low_text_page_numbers.append(page_number)
        pages.append(
            PageText(
                page_number=page_number,
                text=text,
                is_empty=is_empty,
                is_low_text=is_low_text,
                headings=headings,
            )
        )

    if low_text_page_numbers:
        logger.warning(
            "pdf_low_text_pages_detected",
            page_numbers=low_text_page_numbers,
            page_count=len(pages),
        )

    return ExtractionResult(pages=pages, page_count=len(pages))


def extract_pdf(
    content: bytes,
    *,
    timeout_seconds: int,
    max_pages: int,
    min_extractable_chars_per_page: int,
) -> ExtractionResult:
    """Extract and clean per-page text from a PDF's raw bytes.

    Raises CorruptPdfError, PdfTooManyPagesError, or
    PdfProcessingTimeoutError — all caught by the ingestion pipeline to
    mark the document FAILED without affecting other documents.
    """
    try:
        doc = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:
        raise CorruptPdfError() from exc

    if doc.page_count == 0:
        doc.close()
        raise CorruptPdfError()
    if doc.page_count > max_pages:
        page_count = doc.page_count
        doc.close()
        raise PdfTooManyPagesError(f"PDF has {page_count} pages; maximum allowed is {max_pages}.")

    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(
        _extract_all_pages, doc, min_extractable_chars_per_page=min_extractable_chars_per_page
    )
    try:
        result = future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        # The worker thread may still be reading `doc` natively — closing
        # it here would race with that thread and can crash the process.
        # Deliberately leak the handle and executor; best-effort per
        # Section 11.4 (no OS-level sandbox in this phase).
        logger.error("pdf_processing_timeout", timeout_seconds=timeout_seconds)
        raise PdfProcessingTimeoutError() from exc
    except Exception as exc:
        executor.shutdown(wait=False)
        doc.close()
        raise CorruptPdfError() from exc
    else:
        executor.shutdown(wait=False)
        doc.close()
        return result
