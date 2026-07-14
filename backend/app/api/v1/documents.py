"""GET/DELETE /api/v1/documents (SDD Section 10.3, 10.4)."""

import uuid

from fastapi import APIRouter, Query

from app.api.deps import CurrentTenantIdDep, DocumentRepositoryDep, SettingsDep
from app.api.schemas.documents import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentSummary,
)
from app.core.constants import DocumentStatus
from app.core.exceptions import DocumentNotFoundError, DocumentProcessingError
from app.services.storage_service import StorageService
from app.services.vector_store import ChromaVectorStore

router = APIRouter()

# "Mid-ingestion" per FR-D07/10.4 means actively being processed; UPLOADED
# (not yet started) and READY/FAILED (finished, one way or the other) are
# all safely deletable. Only these transitional states are blocked.
_MID_INGESTION_STATUSES = (
    DocumentStatus.PARSING,
    DocumentStatus.CHUNKING,
    DocumentStatus.EMBEDDING,
)


@router.get("/documents")
async def list_documents(
    tenant_id: CurrentTenantIdDep,
    document_repo: DocumentRepositoryDep,
    status: DocumentStatus | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> DocumentListResponse:
    items, total = document_repo.list(tenant_id, status=status, page=page, page_size=page_size)
    return DocumentListResponse(
        items=[DocumentSummary.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: uuid.UUID,
    tenant_id: CurrentTenantIdDep,
    document_repo: DocumentRepositoryDep,
    settings: SettingsDep,
) -> DocumentDeleteResponse:
    document = document_repo.get(tenant_id, document_id)
    if document is None:
        raise DocumentNotFoundError()

    if document.status in _MID_INGESTION_STATUSES:
        raise DocumentProcessingError()

    storage_path = document.storage_path
    chunks_removed = document_repo.delete(document)
    StorageService(settings).delete(storage_path)
    ChromaVectorStore(settings).delete_by_document(tenant_id=tenant_id, document_id=document_id)
    return DocumentDeleteResponse(document_id=document_id, chunks_removed=chunks_removed)
