"""Unit tests for app/rag/pdf_processor.py (SDD Section 7.2 Stage 2).

Most behaviors are exercised through real, small PDFs built in-memory
with PyMuPDF (`fitz`) so the tests cover the actual extraction path.
Hyphenation repair and text normalization are tested directly against
their pure-function implementations instead: PyMuPDF's layout engine
doesn't offer a reliable, deterministic way to force a "wrapped-word"
hyphen break from synthetic `insert_text` calls, whereas the functions
themselves are simple and worth covering precisely.
"""

import time

import fitz
import pytest

from app.core.exceptions import CorruptPdfError, PdfProcessingTimeoutError, PdfTooManyPagesError
from app.rag import pdf_processor

_DEFAULT_KWARGS = {
    "timeout_seconds": 10,
    "max_pages": 50,
    "min_extractable_chars_per_page": 20,
}


def _build_pdf(page_builder) -> bytes:
    """page_builder(doc) adds one or more pages; returns the PDF bytes."""
    doc = fitz.open()
    page_builder(doc)
    content = doc.tobytes()
    doc.close()
    return content


def test_extracts_pages_with_correct_page_numbers_and_text():
    def build(doc: fitz.Document) -> None:
        p1 = doc.new_page(width=612, height=792)
        p1.insert_text((72, 100), "First page body text.", fontsize=11, fontname="helv")
        p2 = doc.new_page(width=612, height=792)
        p2.insert_text((72, 100), "Second page body text.", fontsize=11, fontname="helv")

    result = pdf_processor.extract_pdf(_build_pdf(build), **_DEFAULT_KWARGS)

    assert result.page_count == 2
    assert [p.page_number for p in result.pages] == [1, 2]
    assert "First page body text." in result.pages[0].text
    assert "Second page body text." in result.pages[1].text


def test_strips_repeated_header_and_footer_lines():
    def build(doc: fitz.Document) -> None:
        for i in range(1, 5):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 50), "Acme Corp HR Policy", fontsize=11, fontname="helv")
            page.insert_text(
                (72, 400), f"Body content unique to page {i}.", fontsize=11, fontname="helv"
            )
            page.insert_text((72, 740), f"Page {i} of 4", fontsize=11, fontname="helv")

    result = pdf_processor.extract_pdf(_build_pdf(build), **_DEFAULT_KWARGS)

    assert result.page_count == 4
    for i, page in enumerate(result.pages, start=1):
        assert "Acme Corp HR Policy" not in page.text
        assert "of 4" not in page.text
        assert f"Body content unique to page {i}." in page.text


def test_empty_page_is_flagged_without_low_text_flag():
    def build(doc: fitz.Document) -> None:
        doc.new_page(width=612, height=792)

    result = pdf_processor.extract_pdf(_build_pdf(build), **_DEFAULT_KWARGS)

    page = result.pages[0]
    assert page.is_empty is True
    assert page.text == ""
    assert page.is_low_text is False


def test_image_only_page_is_flagged_low_text():
    def build(doc: fitz.Document) -> None:
        page = doc.new_page(width=200, height=200)
        pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 10, 10))
        pix.clear_with(128)
        page.insert_image(fitz.Rect(10, 10, 100, 100), stream=pix.tobytes("png"))

    result = pdf_processor.extract_pdf(_build_pdf(build), **_DEFAULT_KWARGS)

    page = result.pages[0]
    assert page.is_low_text is True


def test_page_with_image_and_sparse_caption_is_flagged_low_text():
    def build(doc: fitz.Document) -> None:
        page = doc.new_page(width=200, height=200)
        pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, 10, 10))
        pix.clear_with(128)
        page.insert_image(fitz.Rect(10, 10, 100, 100), stream=pix.tobytes("png"))
        page.insert_text((10, 150), "Fig 1", fontsize=8, fontname="helv")

    result = pdf_processor.extract_pdf(
        _build_pdf(build), timeout_seconds=10, max_pages=50, min_extractable_chars_per_page=20
    )

    page = result.pages[0]
    assert page.is_low_text is True


def test_heading_detected_via_larger_font_size():
    def build(doc: fitz.Document) -> None:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 80), "Leave Policy", fontsize=20, fontname="helv")
        page.insert_text(
            (72, 140),
            "Employees receive twelve days of annual leave per year under this policy.",
            fontsize=11,
            fontname="helv",
        )

    result = pdf_processor.extract_pdf(_build_pdf(build), **_DEFAULT_KWARGS)

    page = result.pages[0]
    assert len(page.headings) == 1
    heading = page.headings[0]
    assert heading.title == "Leave Policy"
    assert page.text[heading.offset : heading.offset + len(heading.title)] == heading.title


def test_corrupt_pdf_raises_corrupt_pdf_error():
    with pytest.raises(CorruptPdfError):
        pdf_processor.extract_pdf(b"not a pdf at all", **_DEFAULT_KWARGS)


def test_too_many_pages_raises():
    def build(doc: fitz.Document) -> None:
        for _ in range(3):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 100), "content", fontsize=11, fontname="helv")

    with pytest.raises(PdfTooManyPagesError):
        pdf_processor.extract_pdf(
            _build_pdf(build), timeout_seconds=10, max_pages=2, min_extractable_chars_per_page=20
        )


def test_extraction_timeout_raises(monkeypatch: pytest.MonkeyPatch):
    def build(doc: fitz.Document) -> None:
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), "content", fontsize=11, fontname="helv")

    def _slow_extract(doc, *, min_extractable_chars_per_page):
        time.sleep(0.5)
        return pdf_processor.ExtractionResult(pages=[], page_count=0)

    monkeypatch.setattr(pdf_processor, "_extract_all_pages", _slow_extract)

    with pytest.raises(PdfProcessingTimeoutError):
        pdf_processor.extract_pdf(
            _build_pdf(build),
            timeout_seconds=0.05,
            max_pages=50,
            min_extractable_chars_per_page=20,
        )


class TestRepairHyphenation:
    def test_joins_wrapped_word(self):
        assert pdf_processor._repair_hyphenation("compen-\nsation") == "compensation"

    def test_leaves_normal_hyphen_at_end_of_sentence_alone(self):
        # No following lowercase letter on the next line -> not touched.
        text = "This is a well-\nKnown policy."
        assert pdf_processor._repair_hyphenation(text) == text


class TestNormalizeText:
    def test_collapses_whitespace_and_blank_lines(self):
        raw = "Line one\n\n\n\nLine two"
        assert pdf_processor._normalize_text(raw) == "Line one\n\nLine two"

    def test_normalizes_bullets(self):
        assert pdf_processor._normalize_text("• Item one") == "- Item one"
