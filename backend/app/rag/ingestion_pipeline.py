"""Background ingestion pipeline (SDD Section 7, Section 9: ingestion_pipeline.py).

Runs as a FastAPI BackgroundTask scheduled by POST /upload after a file
passes validation. Owns the document status machine end to end:
UPLOADED -> PARSING -> CHUNKING -> EMBEDDING -> READY, or FAILED at any
stage with a recorded failure_reason.

Opens its own DB session and StorageService rather than reusing
request-scoped ones: a background task can run after the request that
scheduled it has already finished. The embedder is reached via the
process-wide registry (app.embeddings.registry), not threaded through
as a parameter, since it has no per-request-relevant state - same
reasoning as reaching the DB via get_session_factory().
"""

import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.constants import DocumentStatus
from app.core.exceptions import DomainError
from app.core.logging import get_logger
from app.database.models import Document
from app.database.repositories.chunks import ChunkRepository
from app.database.session import get_session_factory
from app.embeddings.registry import get_embedder
from app.rag import chunker, metadata, pdf_processor
from app.services.storage_service import StorageService
from app.services.vector_store import ChromaVectorStore

logger = get_logger(__name__)


def run_ingestion(
    document_id: uuid.UUID, tenant_id: uuid.UUID, settings: Settings | None = None
) -> None:
    settings = settings or get_settings()
    db = get_session_factory()()
    try:
        document = db.get(Document, document_id)
        if document is None or document.tenant_id != tenant_id:
            logger.warning("ingestion_document_not_found", document_id=str(document_id))
            return

        started_at = time.perf_counter()
        storage = StorageService(settings)
        try:
            _run_stages(document, db, storage, settings)
        except DomainError as exc:
            document.status = DocumentStatus.FAILED
            document.failure_reason = exc.message
            db.commit()
            logger.warning(
                "ingestion_failed",
                document_id=str(document_id),
                error_code=exc.code,
                reason=exc.message,
            )
            return
        except Exception as exc:  # noqa: BLE001 - isolate this document's failure only
            # No half-indexed documents (SDD Stage 6): purge both the
            # relational chunks and any partial vectors already written.
            ChunkRepository(db).delete_by_document(document.id)
            ChromaVectorStore(settings).delete_by_document(
                tenant_id=tenant_id, document_id=document.id
            )
            document.status = DocumentStatus.FAILED
            document.failure_reason = (
                "An unexpected error occurred while processing this document."
            )
            db.commit()
            logger.error("ingestion_unexpected_error", document_id=str(document_id), exc_info=exc)
            return

        logger.info(
            "ingestion_completed",
            document_id=str(document_id),
            duration_ms=round((time.perf_counter() - started_at) * 1000),
            chunk_count=document.chunk_count,
        )
    finally:
        db.close()


def _run_stages(
    document: Document, db: Session, storage: StorageService, settings: Settings
) -> None:
    document.status = DocumentStatus.PARSING
    db.commit()
    content = storage.read(document.storage_path)

    extraction = pdf_processor.extract_pdf(
        content,
        timeout_seconds=settings.ingestion_pdf_timeout_seconds,
        max_pages=settings.ingestion_max_pages,
        min_extractable_chars_per_page=settings.min_extractable_chars_per_page,
    )
    document.page_count = extraction.page_count
    document.status = DocumentStatus.CHUNKING
    db.commit()

    raw_chunks = chunker.chunk_pages(
        extraction.pages,
        target_tokens=settings.chunk_target_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    drafts = metadata.build_chunk_drafts(
        raw_chunks, document_id=document.id, tenant_id=document.tenant_id
    )
    chunks = ChunkRepository(db).bulk_create(drafts)

    document.status = DocumentStatus.EMBEDDING
    db.commit()

    embedder = get_embedder()
    embeddings = embedder.embed_passages([chunk.text for chunk in chunks])
    ChromaVectorStore(settings).add_chunks(
        tenant_id=document.tenant_id,
        document_name=document.display_name,
        chunks=chunks,
        embeddings=embeddings,
    )

    # The documents row flips to READY only after the full Chroma batch
    # above has committed (SDD Stage 6) - any exception before this point
    # is caught by run_ingestion's generic handler, which purges both the
    # chunks just persisted and any partial vectors already written.
    document.chunk_count = len(chunks)
    document.status = DocumentStatus.READY
    document.ready_at = datetime.now(UTC)
    db.commit()
