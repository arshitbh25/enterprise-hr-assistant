"""Unit tests for app/services/vector_store.py (SDD Section 7.2 Stage 6).

Uses hand-built, clearly-separated synthetic 384-d vectors (one-hot at
different dimensions) instead of the real embedding model - this file
only exercises the Chroma plumbing (add/query/delete/heartbeat), so it
stays fast and independent of model loading.
"""

import uuid

import pytest

from app.core.config import Settings
from app.database.models import Chunk
from app.services.vector_store import ChromaVectorStore

_DIMENSION = 384


def _one_hot(index: int) -> list[float]:
    vector = [0.0] * _DIMENSION
    vector[index] = 1.0
    return vector


def _chunk(**overrides) -> Chunk:
    defaults = dict(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        chunk_index=0,
        text="Employees receive twelve days of annual leave.",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        token_count=8,
        embedding_model="bge-small-en-v1.5",
        content_hash="a" * 64,
    )
    defaults.update(overrides)
    return Chunk(**defaults)


@pytest.fixture()
def store(tmp_path) -> ChromaVectorStore:
    settings = Settings(_env_file=None, chroma_dir=str(tmp_path))
    return ChromaVectorStore(settings)


def test_add_and_query_returns_nearest_neighbor(store: ChromaVectorStore):
    tenant_id = uuid.uuid4()
    leave_chunk = _chunk(text="Leave policy chunk", section_title="Leave Policy")
    dress_chunk = _chunk(text="Dress code chunk", section_title="Dress Code")

    store.add_chunks(
        tenant_id=tenant_id,
        document_name="Leave_Policy.pdf",
        chunks=[leave_chunk],
        embeddings=[_one_hot(0)],
    )
    store.add_chunks(
        tenant_id=tenant_id,
        document_name="Dress_Code.pdf",
        chunks=[dress_chunk],
        embeddings=[_one_hot(1)],
    )

    [top_hit] = store.query(tenant_id=tenant_id, query_embedding=_one_hot(0), top_k=1)

    assert top_hit.chunk_id == leave_chunk.id
    assert top_hit.document_name == "Leave_Policy.pdf"
    assert top_hit.text == "Leave policy chunk"
    assert top_hit.section_title == "Leave Policy"
    assert top_hit.page_start == 1


def test_delete_by_document_removes_only_that_documents_vectors(store: ChromaVectorStore):
    tenant_id = uuid.uuid4()
    document_a_id = uuid.uuid4()
    document_b_id = uuid.uuid4()
    chunk_a = _chunk(document_id=document_a_id, text="Document A chunk")
    chunk_b = _chunk(document_id=document_b_id, text="Document B chunk")

    store.add_chunks(
        tenant_id=tenant_id, document_name="a.pdf", chunks=[chunk_a], embeddings=[_one_hot(0)]
    )
    store.add_chunks(
        tenant_id=tenant_id, document_name="b.pdf", chunks=[chunk_b], embeddings=[_one_hot(1)]
    )

    removed = store.delete_by_document(tenant_id=tenant_id, document_id=document_a_id)
    assert removed == 1

    results = store.query(tenant_id=tenant_id, query_embedding=_one_hot(0), top_k=5)
    assert all(hit.document_id != document_a_id for hit in results)
    assert any(hit.document_id == document_b_id for hit in results)


def test_delete_by_document_with_no_vectors_returns_zero(store: ChromaVectorStore):
    assert store.delete_by_document(tenant_id=uuid.uuid4(), document_id=uuid.uuid4()) == 0


def test_add_chunks_with_empty_list_is_a_noop(store: ChromaVectorStore):
    store.add_chunks(tenant_id=uuid.uuid4(), document_name="x.pdf", chunks=[], embeddings=[])


def test_query_on_empty_collection_returns_empty_list(store: ChromaVectorStore):
    assert store.query(tenant_id=uuid.uuid4(), query_embedding=_one_hot(0)) == []


def test_heartbeat_returns_true(store: ChromaVectorStore):
    assert store.heartbeat() is True
