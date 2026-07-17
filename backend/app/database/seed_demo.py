"""Idempotent startup seed: bundled demo document (Hugging Face Spaces
ephemeral storage, ADR-012).

Spaces' free tier resets the container filesystem on every restart/
rebuild, so the deployed demo would otherwise boot with zero documents
after any redeploy. This re-ingests a bundled sample PDF on cold start
so the demo is never empty. Reuses the exact upload path (StorageService
+ DocumentRepository + run_ingestion) rather than a second ingestion
mechanism - this is only a startup-time caller of the real one, mirroring
upload.py's `_process_one_file` flow.
"""

import hashlib
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.database.repositories.documents import DocumentRepository
from app.rag.ingestion_pipeline import run_ingestion
from app.services.storage_service import StorageService

logger = get_logger(__name__)

_SEED_DIR = Path(__file__).resolve().parents[2] / "seed_data"
_SEED_PDF = _SEED_DIR / "Acme_Corp_HR_Policy_Handbook_2026.pdf"


def seed_demo_document(db: Session, settings: Settings) -> None:
    if not settings.seed_demo_document:
        return

    tenant_id = uuid.UUID(settings.default_tenant_id)
    user_id = uuid.UUID(settings.default_user_id)

    content = _SEED_PDF.read_bytes()
    content_hash = hashlib.sha256(content).hexdigest()

    document_repo = DocumentRepository(db)
    if document_repo.get_by_content_hash(tenant_id, content_hash) is not None:
        logger.info("demo_document_already_seeded")
        return

    storage_path = f"uploads/{tenant_id}/{content_hash}_{_SEED_PDF.name}"
    StorageService(settings).save(storage_path, content)

    document = document_repo.create(
        tenant_id=tenant_id,
        uploaded_by=user_id,
        file_name=_SEED_PDF.name,
        display_name=_SEED_PDF.name,
        storage_path=storage_path,
        content_hash=content_hash,
        size_bytes=len(content),
    )
    run_ingestion(document_id=document.id, tenant_id=tenant_id, settings=settings)
    logger.info("demo_document_seeded", document_id=str(document.id))
