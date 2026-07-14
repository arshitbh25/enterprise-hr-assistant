"""Retriever Agent (SDD Section 6.3.3, Section 7.2 Stage 7).

Embeds the question with the same BGE model used at ingestion time and
runs a tenant-filtered ChromaDB similarity search. This is the one place
in the RAG pipeline that knows about Chroma's distance-metric quirk (see
_similarity_from_distance below) - everything downstream (ranking,
prompt building, citations) works with a plain 0-1 similarity score and
never touches Chroma's distance convention directly.
"""

import uuid
from dataclasses import dataclass

from app.core.config import Settings
from app.core.exceptions import VectorStoreUnavailableError
from app.core.logging import get_logger
from app.embeddings.registry import get_embedder
from app.services.vector_store import ChromaVectorStore, RetrievedVector

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_start: int
    page_end: int
    section_title: str | None
    text: str
    score: float  # normalized cosine similarity, 0..1, higher = more relevant


def _similarity_from_distance(distance: float) -> float:
    """Chroma's `cosine` space returns `distance = 1 - cosine_similarity`.
    Verified directly in tests/unit/test_rag_retriever.py against a
    real embedder + real Chroma round-trip, comparing to an
    independently-computed cosine similarity (numpy dot product on
    L2-normalized vectors)."""
    return max(0.0, 1.0 - distance)


def _to_retrieved_chunk(vector: RetrievedVector) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=vector.chunk_id,
        document_id=vector.document_id,
        document_name=vector.document_name,
        page_start=vector.page_start,
        page_end=vector.page_end,
        section_title=vector.section_title,
        text=vector.text,
        score=_similarity_from_distance(vector.distance),
    )


def retrieve(
    question: str, *, tenant_id: uuid.UUID, settings: Settings
) -> list[RetrievedChunk]:
    query_embedding = get_embedder().embed_query(question)
    store = ChromaVectorStore(settings)

    try:
        vectors = store.query(
            tenant_id=tenant_id, query_embedding=query_embedding, top_k=settings.retrieval_top_k
        )
    except Exception:  # noqa: BLE001 - first failure is retried once below
        logger.warning("retrieval_query_failed_retrying", tenant_id=str(tenant_id))
        try:
            vectors = store.query(
                tenant_id=tenant_id,
                query_embedding=query_embedding,
                top_k=settings.retrieval_top_k,
            )
        except Exception as exc:
            logger.error("retrieval_query_failed", tenant_id=str(tenant_id), exc_info=exc)
            raise VectorStoreUnavailableError() from exc

    return [_to_retrieved_chunk(vector) for vector in vectors]
