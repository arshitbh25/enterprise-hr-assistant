"""Rebuild the ChromaDB vector index from the relational DB (ADR-005).

The relational DB (`documents` + `chunks`) is the system of record;
ChromaDB is a derived, rebuildable index. Run this after a Chroma
data-loss event, corruption, or an embedding-model change - it never
reads from the existing Chroma collection, only from `documents` and
`chunks`.

Usage (from backend/):
    python scripts/rebuild_index.py
"""

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.config import Settings, get_settings  # noqa: E402
from app.core.constants import DocumentStatus  # noqa: E402
from app.database.models import Chunk, Document  # noqa: E402
from app.database.session import get_session_factory, init_engine  # noqa: E402
from app.embeddings.embedder import Embedder  # noqa: E402
from app.embeddings.registry import get_embedder, init_embedder  # noqa: E402
from app.services.vector_store import ChromaVectorStore  # noqa: E402


def _rebuild_tenant(
    db: Session, vector_store: ChromaVectorStore, embedder: Embedder, tenant_id
) -> tuple[int, int]:
    vector_store.reset_collection(tenant_id)

    documents = db.scalars(
        select(Document).where(
            Document.tenant_id == tenant_id, Document.status == DocumentStatus.READY
        )
    ).all()

    chunk_count = 0
    for document in documents:
        chunks = db.scalars(
            select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
        ).all()
        if not chunks:
            continue

        embeddings = embedder.embed_passages([chunk.text for chunk in chunks])
        vector_store.add_chunks(
            tenant_id=tenant_id,
            document_name=document.display_name,
            chunks=chunks,
            embeddings=embeddings,
        )
        chunk_count += len(chunks)

    return len(documents), chunk_count


def rebuild_index(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    init_engine(settings)
    init_embedder(settings)

    db = get_session_factory()()
    try:
        tenant_ids = db.scalars(
            select(Document.tenant_id).where(Document.status == DocumentStatus.READY).distinct()
        ).all()

        if not tenant_ids:
            print("No READY documents found; nothing to rebuild.")
            return

        embedder = get_embedder()
        vector_store = ChromaVectorStore(settings)

        for tenant_id in tenant_ids:
            document_count, chunk_count = _rebuild_tenant(db, vector_store, embedder, tenant_id)
            print(
                f"Tenant {tenant_id}: re-indexed {document_count} document(s), "
                f"{chunk_count} chunk(s)."
            )
    finally:
        db.close()


if __name__ == "__main__":
    rebuild_index()
