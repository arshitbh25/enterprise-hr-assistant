"""Unit tests for app/rag/retriever.py (SDD Section 6.3.3, 7.2 Stage 7).

Uses the real embedder and a real temp-dir ChromaDB - this is the module
that owns Chroma's distance-metric conversion, so it's worth verifying
against real embeddings rather than synthetic vectors alone.
"""

import uuid

import numpy as np
import pytest

from app.core.config import Settings
from app.core.exceptions import VectorStoreUnavailableError
from app.database.models import Chunk
from app.embeddings.registry import get_embedder
from app.rag.retriever import _similarity_from_distance, retrieve
from app.services.vector_store import ChromaVectorStore

pytestmark = pytest.mark.model


def _chunk(**overrides) -> Chunk:
    defaults = dict(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        chunk_index=0,
        text="Employees receive twelve days of annual leave per year.",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        token_count=10,
        embedding_model="bge-small-en-v1.5",
        content_hash="a" * 64,
    )
    defaults.update(overrides)
    return Chunk(**defaults)


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(_env_file=None, chroma_dir=str(tmp_path / "chroma"))


def test_similarity_from_distance_matches_real_chroma_round_trip(settings: Settings):
    embedder = get_embedder()
    passage_vector = embedder.embed_passages(["Employees receive twelve days of annual leave."])[
        0
    ]
    query_vector = embedder.embed_query("how many casual leaves do I get")

    direct_cosine_similarity = float(np.dot(passage_vector, query_vector))

    tenant_id = uuid.uuid4()
    chunk = _chunk(tenant_id=tenant_id, text="Employees receive twelve days of annual leave.")
    store = ChromaVectorStore(settings)
    store.add_chunks(
        tenant_id=tenant_id,
        document_name="doc.pdf",
        chunks=[chunk],
        embeddings=[passage_vector],
    )

    [hit] = store.query(tenant_id=tenant_id, query_embedding=query_vector, top_k=1)
    converted_similarity = _similarity_from_distance(hit.distance)

    assert converted_similarity == pytest.approx(direct_cosine_similarity, abs=1e-4)


def test_retrieve_returns_ranked_chunks_with_citation_metadata(settings: Settings):
    tenant_id = uuid.uuid4()
    chunk = _chunk(
        tenant_id=tenant_id,
        text="Employees receive twelve days of annual leave per year.",
        page_start=3,
        page_end=3,
        section_title="Leave Policy",
    )
    embedder = get_embedder()
    embedding = embedder.embed_passages([chunk.text])[0]
    ChromaVectorStore(settings).add_chunks(
        tenant_id=tenant_id,
        document_name="Leave_Policy.pdf",
        chunks=[chunk],
        embeddings=[embedding],
    )

    results = retrieve("how many casual leaves do I get", tenant_id=tenant_id, settings=settings)

    assert len(results) == 1
    [result] = results
    assert result.chunk_id == chunk.id
    assert result.document_id == chunk.document_id
    assert result.document_name == "Leave_Policy.pdf"
    assert result.page_start == 3
    assert result.page_end == 3
    assert result.section_title == "Leave Policy"
    assert 0.0 <= result.score <= 1.0


def test_retrieve_returns_empty_list_for_tenant_with_no_vectors(settings: Settings):
    assert retrieve("anything", tenant_id=uuid.uuid4(), settings=settings) == []


def test_retrieve_retries_once_then_succeeds(settings: Settings, monkeypatch: pytest.MonkeyPatch):
    tenant_id = uuid.uuid4()
    chunk = _chunk(tenant_id=tenant_id)
    embedder = get_embedder()
    embedding = embedder.embed_passages([chunk.text])[0]
    ChromaVectorStore(settings).add_chunks(
        tenant_id=tenant_id, document_name="doc.pdf", chunks=[chunk], embeddings=[embedding]
    )

    real_query = ChromaVectorStore.query
    call_count = {"n": 0}

    def _flaky_query(self, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient Chroma error")
        return real_query(self, **kwargs)

    monkeypatch.setattr(ChromaVectorStore, "query", _flaky_query)

    results = retrieve("leave", tenant_id=tenant_id, settings=settings)

    assert len(results) == 1
    assert call_count["n"] == 2


def test_retrieve_raises_vector_store_unavailable_after_two_failures(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    def _always_fail(self, **kwargs):
        raise RuntimeError("simulated persistent Chroma error")

    monkeypatch.setattr(ChromaVectorStore, "query", _always_fail)

    with pytest.raises(VectorStoreUnavailableError):
        retrieve("leave", tenant_id=uuid.uuid4(), settings=settings)
