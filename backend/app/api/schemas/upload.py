"""Schemas for POST /api/v1/upload (SDD Section 10.1)."""

import uuid

from pydantic import BaseModel


class UploadFileError(BaseModel):
    code: str
    message: str


class UploadFileResult(BaseModel):
    file_name: str
    document_id: uuid.UUID | None = None
    status: str
    error: UploadFileError | None = None


class UploadResponse(BaseModel):
    results: list[UploadFileResult]
    request_id: str | None = None
