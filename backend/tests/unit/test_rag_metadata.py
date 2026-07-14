"""Unit tests for app/rag/metadata.py (SDD Section 8.3)."""

import hashlib
import uuid

from app.core.constants import EMBEDDING_MODEL_NAME
from app.rag.chunker import RawChunk
from app.rag.metadata import build_chunk_drafts

_DOCUMENT_ID = uuid.uuid4()
_TENANT_ID = uuid.uuid4()


def _raw_chunk(**overrides) -> RawChunk:
    defaults = dict(
        text="Employees receive twelve days of annual leave per year.",
        char_start=0,
        char_end=57,
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        chunk_index=0,
        token_count=11,
    )
    defaults.update(overrides)
    return RawChunk(**defaults)


def test_build_chunk_drafts_populates_all_fields():
    raw_chunk = _raw_chunk()

    [draft] = build_chunk_drafts([raw_chunk], document_id=_DOCUMENT_ID, tenant_id=_TENANT_ID)

    assert draft.document_id == _DOCUMENT_ID
    assert draft.tenant_id == _TENANT_ID
    assert draft.chunk_index == raw_chunk.chunk_index
    assert draft.text == raw_chunk.text
    assert draft.page_start == raw_chunk.page_start
    assert draft.page_end == raw_chunk.page_end
    assert draft.section_title == raw_chunk.section_title
    assert draft.token_count == raw_chunk.token_count
    assert draft.embedding_model == EMBEDDING_MODEL_NAME
    assert draft.content_hash == hashlib.sha256(raw_chunk.text.encode("utf-8")).hexdigest()


def test_content_hash_is_deterministic_and_content_sensitive():
    chunk_a = _raw_chunk(text="Same text", chunk_index=0)
    chunk_b = _raw_chunk(text="Same text", chunk_index=1)
    chunk_c = _raw_chunk(text="Different text", chunk_index=2)

    drafts = build_chunk_drafts(
        [chunk_a, chunk_b, chunk_c], document_id=_DOCUMENT_ID, tenant_id=_TENANT_ID
    )

    assert drafts[0].content_hash == drafts[1].content_hash
    assert drafts[0].content_hash != drafts[2].content_hash


def test_section_title_none_is_preserved():
    raw_chunk = _raw_chunk(section_title=None)

    [draft] = build_chunk_drafts([raw_chunk], document_id=_DOCUMENT_ID, tenant_id=_TENANT_ID)

    assert draft.section_title is None


def test_empty_input_returns_empty_list():
    assert build_chunk_drafts([], document_id=_DOCUMENT_ID, tenant_id=_TENANT_ID) == []
