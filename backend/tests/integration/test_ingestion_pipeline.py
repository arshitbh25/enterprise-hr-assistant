"""Integration test: the full Phase 3+4 ingestion pipeline against a
real temp SQLite DB, real temp file storage, and a real temp ChromaDB -
no mocking of PyMuPDF, the chunker, the embedder, or the repositories.
Exercises the P3 exit criterion (SDD Section 13, a generated fixture
PDF reaches READY with verified page mapping, well under the 60s /
100-page budget) and the P4 exit criteria (delete removes all vectors;
a retrieval smoke test returns the expected chunk for a known query).
"""

import hashlib
import time
import uuid
from pathlib import Path

import fitz
import pytest
from sqlalchemy import select

from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.core.constants import DocumentStatus
from app.database.models import Chunk
from app.database.repositories.documents import DocumentRepository
from app.database.seed import seed_defaults
from app.database.session import get_session_factory, init_engine
from app.embeddings.registry import get_embedder
from app.rag.ingestion_pipeline import run_ingestion
from app.services.storage_service import StorageService
from app.services.vector_store import ChromaVectorStore

pytestmark = pytest.mark.model

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


_TOPICS = [
    "Leave Policy",
    "Code of Conduct",
    "Reimbursement Rules",
    "Benefits Overview",
    "Offboarding Process",
]


def _build_fixture_pdf(num_pages: int) -> bytes:
    """Each page gets a distinct heading/body pulled from a small topic
    cycle - never identical (or digit-only-varying) across pages, so the
    header/footer repeated-line detector has nothing legitimate to strip.
    """
    doc = fitz.open()
    for i in range(num_pages):
        topic = _TOPICS[i % len(_TOPICS)]
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 80), topic, fontsize=18, fontname="helv")
        page.insert_text(
            (72, 120),
            f"This section explains the {topic.lower()} in detail for all "
            "employees at the company. " * 15,
            fontsize=11,
            fontname="helv",
        )
    content = doc.tobytes()
    doc.close()
    return content


@pytest.fixture()
def pipeline_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    db_path = tmp_path / "ingestion_test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    storage_dir = tmp_path / "storage"
    chroma_dir = tmp_path / "chroma"

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        storage_dir=str(storage_dir),
        chroma_dir=str(chroma_dir),
    )
    init_engine(settings)
    return settings


def _seeded_document(settings: Settings, *, content: bytes, file_name: str = "policy.pdf"):
    db = get_session_factory()()
    try:
        seed_defaults(db, settings)
        tenant_id = uuid.UUID(settings.default_tenant_id)
        user_id = uuid.UUID(settings.default_user_id)

        storage = StorageService(settings)
        storage_path = f"uploads/{tenant_id}/{file_name}"
        storage.save(storage_path, content)

        document = DocumentRepository(db).create(
            tenant_id=tenant_id,
            uploaded_by=user_id,
            file_name=file_name,
            display_name=file_name,
            storage_path=storage_path,
            content_hash=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
        return document.id, tenant_id
    finally:
        db.close()


def test_ingestion_reaches_ready_with_correct_page_mapping(pipeline_settings: Settings):
    document_id, tenant_id = _seeded_document(pipeline_settings, content=_build_fixture_pdf(5))

    run_ingestion(document_id, tenant_id, settings=pipeline_settings)

    db = get_session_factory()()
    try:
        document = DocumentRepository(db).get(tenant_id, document_id)
        assert document.status == DocumentStatus.READY
        assert document.failure_reason is None
        assert document.page_count == 5
        assert document.chunk_count > 0
        assert document.ready_at is not None

        chunks = db.scalars(select(Chunk).where(Chunk.document_id == document_id)).all()
        assert len(chunks) == document.chunk_count
        pages_covered = {p for c in chunks for p in range(c.page_start, c.page_end + 1)}
        assert pages_covered == {1, 2, 3, 4, 5}
        for chunk in chunks:
            assert chunk.embedding_model == "bge-small-en-v1.5"
            assert chunk.content_hash
    finally:
        db.close()

    # P4 exit criterion: a retrieval smoke test returns the expected
    # chunk for a known query against real ingested content.
    store = ChromaVectorStore(pipeline_settings)
    query_vector = get_embedder().embed_query("What is the leave policy for employees?")
    results = store.query(tenant_id=tenant_id, query_embedding=query_vector, top_k=3)

    assert results
    assert results[0].document_id == document_id
    assert "leave policy" in results[0].text.lower()


def test_corrupt_pdf_fails_without_affecting_other_documents(pipeline_settings: Settings):
    good_id, tenant_id = _seeded_document(
        pipeline_settings, content=_build_fixture_pdf(2), file_name="good.pdf"
    )
    bad_id, _ = _seeded_document(
        pipeline_settings, content=b"not a pdf at all", file_name="bad.pdf"
    )

    run_ingestion(bad_id, tenant_id, settings=pipeline_settings)
    run_ingestion(good_id, tenant_id, settings=pipeline_settings)

    db = get_session_factory()()
    try:
        repo = DocumentRepository(db)
        bad_document = repo.get(tenant_id, bad_id)
        good_document = repo.get(tenant_id, good_id)

        assert bad_document.status == DocumentStatus.FAILED
        assert bad_document.failure_reason
        assert bad_document.chunk_count == 0

        assert good_document.status == DocumentStatus.READY
        assert good_document.chunk_count > 0
    finally:
        db.close()


def test_hundred_page_pdf_completes_well_under_budget(pipeline_settings: Settings):
    document_id, tenant_id = _seeded_document(
        pipeline_settings, content=_build_fixture_pdf(100), file_name="large.pdf"
    )

    started_at = time.perf_counter()
    run_ingestion(document_id, tenant_id, settings=pipeline_settings)
    duration_seconds = time.perf_counter() - started_at

    db = get_session_factory()()
    try:
        document = DocumentRepository(db).get(tenant_id, document_id)
        assert document.status == DocumentStatus.READY
        assert document.page_count == 100
    finally:
        db.close()

    assert duration_seconds < 60, f"ingestion took {duration_seconds:.1f}s, exceeds P3 budget"


def test_deleting_document_vectors_leaves_none_for_that_document(pipeline_settings: Settings):
    document_id, tenant_id = _seeded_document(pipeline_settings, content=_build_fixture_pdf(2))
    run_ingestion(document_id, tenant_id, settings=pipeline_settings)

    store = ChromaVectorStore(pipeline_settings)
    probe_embedding = [1.0] + [0.0] * 383

    before = store.query(tenant_id=tenant_id, query_embedding=probe_embedding, top_k=10)
    assert any(hit.document_id == document_id for hit in before)

    removed = store.delete_by_document(tenant_id=tenant_id, document_id=document_id)
    assert removed > 0

    after = store.query(tenant_id=tenant_id, query_embedding=probe_embedding, top_k=10)
    assert all(hit.document_id != document_id for hit in after)


def test_embedding_failure_purges_chunks_and_vectors_leaving_nothing_orphaned(
    pipeline_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    """SDD Stage 6: 'no half-indexed documents.' Wraps the real
    add_chunks (so vectors are genuinely written first) and then raises,
    proving the failure handler's purge removes real, already-written
    vectors - not just a trivial no-op on an empty collection."""
    document_id, tenant_id = _seeded_document(pipeline_settings, content=_build_fixture_pdf(2))

    real_add_chunks = ChromaVectorStore.add_chunks

    def _add_then_fail(self: ChromaVectorStore, **kwargs: object) -> None:
        real_add_chunks(self, **kwargs)
        raise RuntimeError("simulated Chroma failure after a successful write")

    monkeypatch.setattr(ChromaVectorStore, "add_chunks", _add_then_fail)

    run_ingestion(document_id, tenant_id, settings=pipeline_settings)

    db = get_session_factory()()
    try:
        document = DocumentRepository(db).get(tenant_id, document_id)
        assert document.status == DocumentStatus.FAILED
        assert document.failure_reason
        assert document.chunk_count == 0

        orphaned_chunks = db.scalars(select(Chunk).where(Chunk.document_id == document_id)).all()
        assert orphaned_chunks == []
    finally:
        db.close()

    store = ChromaVectorStore(pipeline_settings)
    probe_embedding = [1.0] + [0.0] * 383
    results = store.query(tenant_id=tenant_id, query_embedding=probe_embedding, top_k=10)
    assert all(hit.document_id != document_id for hit in results)
