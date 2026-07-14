"""Chunk metadata assembly (SDD Section 8.3).

Pure function: turns chunker.RawChunk output into fully-populated,
DB-ready chunk drafts. No embedding is computed here - `embedding_model`
just records which model *will* embed this chunk in Phase 4 (the
`chunks.embedding_model` column exists precisely to make that future
swap a re-index job, not a schema change).
"""

import hashlib
import uuid
from dataclasses import dataclass

from app.core.constants import EMBEDDING_MODEL_NAME
from app.rag.chunker import RawChunk


@dataclass(frozen=True)
class ChunkDraft:
    document_id: uuid.UUID
    tenant_id: uuid.UUID
    chunk_index: int
    text: str
    page_start: int
    page_end: int
    section_title: str | None
    token_count: int
    embedding_model: str
    content_hash: str


def build_chunk_drafts(
    raw_chunks: list[RawChunk], *, document_id: uuid.UUID, tenant_id: uuid.UUID
) -> list[ChunkDraft]:
    return [
        ChunkDraft(
            document_id=document_id,
            tenant_id=tenant_id,
            chunk_index=raw_chunk.chunk_index,
            text=raw_chunk.text,
            page_start=raw_chunk.page_start,
            page_end=raw_chunk.page_end,
            section_title=raw_chunk.section_title,
            token_count=raw_chunk.token_count,
            embedding_model=EMBEDDING_MODEL_NAME,
            content_hash=hashlib.sha256(raw_chunk.text.encode("utf-8")).hexdigest(),
        )
        for raw_chunk in raw_chunks
    ]
