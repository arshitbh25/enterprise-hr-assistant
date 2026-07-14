"""POST /api/v1/upload (SDD Section 10.1, Section 7 Stage 1).

Validates each file (magic bytes, size, a lightweight /Encrypt
byte-scan, SHA-256 dedup), persists accepted files to storage, creates
a `documents` row, and schedules the Phase 3 background ingestion
pipeline (parse -> chunk -> READY) per accepted file.
"""

import hashlib
import uuid

from fastapi import APIRouter, BackgroundTasks, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.api.deps import (
    CurrentTenantIdDep,
    CurrentUserIdDep,
    DbSessionDep,
    SettingsDep,
)
from app.api.schemas.upload import UploadFileError, UploadFileResult, UploadResponse
from app.core.config import Settings
from app.core.exceptions import (
    DomainError,
    DuplicateDocumentError,
    EncryptedPdfError,
    FileTooLargeError,
    InvalidFileTypeError,
    ValidationFailedError,
)
from app.core.logging import get_logger, get_request_id
from app.database.repositories.documents import DocumentRepository
from app.rag.ingestion_pipeline import run_ingestion
from app.services.storage_service import StorageService

router = APIRouter()
logger = get_logger(__name__)

_PDF_MAGIC = b"%PDF-"

# A code that every rejected file shares maps to a specific overall status;
# a mixed batch of failures falls back to a generic 400 (SDD 10.1: 400 for
# "no files" is the closest documented code to "nothing usable submitted").
_UNIFORM_FAILURE_STATUS: dict[str, int] = {
    "DUPLICATE_DOCUMENT": 409,
    "FILE_TOO_LARGE": 413,
    "INVALID_FILE_TYPE": 415,
    "ENCRYPTED_PDF": 422,
}


def _process_one_file(
    file: UploadFile,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    max_bytes: int,
    document_repo: DocumentRepository,
    storage: StorageService,
    background_tasks: BackgroundTasks,
    settings: Settings,
) -> UploadFileResult:
    file_name = file.filename or "unnamed.pdf"
    try:
        content = file.file.read()

        if not content.startswith(_PDF_MAGIC):
            raise InvalidFileTypeError()

        if len(content) > max_bytes:
            raise FileTooLargeError()

        if b"/Encrypt" in content:
            raise EncryptedPdfError()

        content_hash = hashlib.sha256(content).hexdigest()

        if document_repo.get_by_content_hash(tenant_id, content_hash) is not None:
            raise DuplicateDocumentError()

        storage_path = f"uploads/{tenant_id}/{content_hash}_{file_name}"
        storage.save(storage_path, content)

        document = document_repo.create(
            tenant_id=tenant_id,
            uploaded_by=user_id,
            file_name=file_name,
            display_name=file_name,
            storage_path=storage_path,
            content_hash=content_hash,
            size_bytes=len(content),
        )
        background_tasks.add_task(
            run_ingestion, document_id=document.id, tenant_id=tenant_id, settings=settings
        )
        return UploadFileResult(
            file_name=file_name, document_id=document.id, status=document.status.value
        )
    except DomainError as exc:
        return UploadFileResult(
            file_name=file_name,
            status="REJECTED",
            error=UploadFileError(code=exc.code, message=exc.message),
        )


@router.post("/upload")
async def upload_documents(
    settings: SettingsDep,
    db: DbSessionDep,
    tenant_id: CurrentTenantIdDep,
    user_id: CurrentUserIdDep,
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(default=[]),
) -> JSONResponse:
    if not files:
        raise ValidationFailedError("At least one file must be provided.", status_code=400)

    if len(files) > settings.upload_max_files:
        raise ValidationFailedError(
            f"A maximum of {settings.upload_max_files} files may be uploaded per request.",
            status_code=400,
        )

    max_bytes = settings.upload_max_file_mb * 1024 * 1024
    document_repo = DocumentRepository(db)
    storage = StorageService(settings)

    results = [
        _process_one_file(
            file,
            tenant_id=tenant_id,
            user_id=user_id,
            max_bytes=max_bytes,
            document_repo=document_repo,
            storage=storage,
            background_tasks=background_tasks,
            settings=settings,
        )
        for file in files
    ]

    accepted = [r for r in results if r.status != "REJECTED"]
    if accepted:
        overall_status = 202
    else:
        error_codes = {r.error.code for r in results if r.error is not None}
        overall_status = (
            _UNIFORM_FAILURE_STATUS.get(next(iter(error_codes)), 400)
            if len(error_codes) == 1
            else 400
        )

    body = UploadResponse(results=results, request_id=get_request_id())
    response = JSONResponse(status_code=overall_status, content=jsonable_encoder(body))
    response.background = background_tasks
    return response
