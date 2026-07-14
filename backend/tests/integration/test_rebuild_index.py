"""Integration test for scripts/rebuild_index.py (ADR-005).

Verifies the rebuild script re-derives Chroma entirely from the
relational DB: a stale/bogus vector seeded directly into Chroma (never
reflected in `documents`/`chunks`) must be gone afterward, and every
real chunk of every READY document must be present and correctly
queryable.
"""

import uuid
from pathlib import Path

import pytest

from alembic import command
from alembic.config import Config
from app.core.config import Settings, get_settings
from app.core.constants import DocumentStatus
from app.database.models import Chunk
from app.database.repositories.chunks import ChunkRepository
from app.database.repositories.documents import DocumentRepository
from app.database.seed import seed_defaults
from app.database.session import get_session_factory, init_engine
from app.rag.metadata import ChunkDraft
from app.services.vector_store import ChromaVectorStore
from scripts.rebuild_index import rebuild_index

pytestmark = pytest.mark.model

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"


@pytest.fixture()
def rebuild_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    db_path = tmp_path / "rebuild_test.db"
    database_url = f"sqlite:///{db_path.as_posix()}"
    chroma_dir = tmp_path / "chroma"

    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        storage_dir=str(tmp_path / "storage"),
        chroma_dir=str(chroma_dir),
    )
    init_engine(settings)
    return settings


def test_rebuild_replaces_stale_vectors_with_real_chunks(rebuild_settings: Settings):
    db = get_session_factory()()
    seed_defaults(db, rebuild_settings)
    tenant_id = uuid.UUID(rebuild_settings.default_tenant_id)
    user_id = uuid.UUID(rebuild_settings.default_user_id)

    document = DocumentRepository(db).create(
        tenant_id=tenant_id,
        uploaded_by=user_id,
        file_name="leave_policy.pdf",
        display_name="Leave Policy",
        storage_path="uploads/leave_policy.pdf",
        content_hash="a" * 64,
        size_bytes=1024,
    )
    document.status = DocumentStatus.READY
    document.chunk_count = 1
    db.commit()

    draft = ChunkDraft(
        document_id=document.id,
        tenant_id=tenant_id,
        chunk_index=0,
        text="Employees receive twelve days of annual leave per year.",
        page_start=1,
        page_end=1,
        section_title="Leave Policy",
        token_count=10,
        embedding_model="bge-small-en-v1.5",
        content_hash="b" * 64,
    )
    [chunk] = ChunkRepository(db).bulk_create([draft])
    db.close()

    # Seed a stale vector directly into Chroma - not reflected in the DB
    # at all - to prove reset_collection actually clears it.
    store = ChromaVectorStore(rebuild_settings)
    stale_chunk = Chunk(
        id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        tenant_id=tenant_id,
        chunk_index=0,
        text="stale orphaned vector",
        page_start=1,
        page_end=1,
        section_title=None,
        token_count=3,
        embedding_model="bge-small-en-v1.5",
        content_hash="c" * 64,
    )
    store.add_chunks(
        tenant_id=tenant_id,
        document_name="Stale.pdf",
        chunks=[stale_chunk],
        embeddings=[[1.0] + [0.0] * 383],
    )

    rebuild_index(rebuild_settings)

    results = store.query(tenant_id=tenant_id, query_embedding=[1.0] + [0.0] * 383, top_k=10)
    result_ids = {hit.chunk_id for hit in results}

    assert stale_chunk.id not in result_ids
    assert chunk.id in result_ids
    real_hit = next(hit for hit in results if hit.chunk_id == chunk.id)
    assert real_hit.document_name == "Leave Policy"
    assert real_hit.text == draft.text


def test_rebuild_with_no_ready_documents_is_a_noop(rebuild_settings: Settings, capsys):
    db = get_session_factory()()
    seed_defaults(db, rebuild_settings)
    db.close()

    rebuild_index(rebuild_settings)

    captured = capsys.readouterr()
    assert "No READY documents found" in captured.out
