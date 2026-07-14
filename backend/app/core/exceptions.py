"""Domain exceptions and the Section 10.8 error envelope.

Every error a client can receive is one of the codes in the catalogue
below. Handlers registered here guarantee that whatever goes wrong —
a known domain failure, a validation error, an unmatched route, or a
genuine bug — always comes back as
``{"error": {"code", "message", "details?"}, "request_id"}`` and never as
a raw stack trace.
"""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, get_request_id

logger = get_logger(__name__)


class DomainError(Exception):
    """Base class for all errors that map to the Section 10.8 error envelope."""

    code: str = "INTERNAL_ERROR"
    status_code: int = 500
    default_message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details
        if status_code is not None:
            # A given error code can carry a different status depending on
            # context (e.g. VALIDATION_FAILED is 422 for a bad field but
            # 400 for "no files provided" per SDD Section 10.1).
            self.status_code = status_code
        super().__init__(self.message)


class InvalidFileTypeError(DomainError):
    code = "INVALID_FILE_TYPE"
    status_code = 415
    default_message = "Only application/pdf files are accepted."


class FileTooLargeError(DomainError):
    code = "FILE_TOO_LARGE"
    status_code = 413
    default_message = "File exceeds the maximum allowed size."


class EncryptedPdfError(DomainError):
    code = "ENCRYPTED_PDF"
    status_code = 422
    default_message = "The uploaded PDF is password-protected."


class CorruptPdfError(DomainError):
    code = "CORRUPT_PDF"
    status_code = 422
    default_message = "The uploaded PDF could not be read; it may be corrupt or empty."


class PdfTooManyPagesError(DomainError):
    code = "PDF_TOO_MANY_PAGES"
    status_code = 422
    default_message = "The PDF exceeds the maximum number of pages allowed."


class PdfProcessingTimeoutError(DomainError):
    code = "PDF_PROCESSING_TIMEOUT"
    status_code = 422
    default_message = "The PDF took too long to process."


class DuplicateDocumentError(DomainError):
    code = "DUPLICATE_DOCUMENT"
    status_code = 409
    default_message = "A document with identical content already exists."


class DocumentNotFoundError(DomainError):
    code = "DOCUMENT_NOT_FOUND"
    status_code = 404
    default_message = "The requested document was not found."


class DocumentProcessingError(DomainError):
    code = "DOCUMENT_PROCESSING"
    status_code = 409
    default_message = "The document is still being processed and cannot be modified yet."


class NoDocumentsIndexedError(DomainError):
    code = "NO_DOCUMENTS_INDEXED"
    status_code = 409
    default_message = "No HR policy documents have been indexed yet."


class SessionNotFoundError(DomainError):
    code = "SESSION_NOT_FOUND"
    status_code = 404
    default_message = "The requested session was not found."


class InvalidQuestionError(DomainError):
    code = "INVALID_QUESTION"
    status_code = 422
    default_message = "The question is empty or exceeds the maximum allowed length."


class RateLimitedError(DomainError):
    code = "RATE_LIMITED"
    status_code = 429
    default_message = "Too many requests. Please slow down and try again shortly."


class LlmQuotaExceededError(DomainError):
    code = "LLM_QUOTA_EXCEEDED"
    status_code = 429
    default_message = "The assistant is busy right now. Please try again in a moment."


class LlmUnavailableError(DomainError):
    code = "LLM_UNAVAILABLE"
    status_code = 503
    default_message = "The assistant is temporarily unavailable. Please try again shortly."


class GenerationTimeoutError(DomainError):
    code = "GENERATION_TIMEOUT"
    status_code = 504
    default_message = "Generating the answer took too long. Please try again."


class VectorStoreUnavailableError(DomainError):
    code = "VECTOR_STORE_UNAVAILABLE"
    status_code = 503
    default_message = "The document search service is temporarily unavailable."


class ValidationFailedError(DomainError):
    code = "VALIDATION_FAILED"
    status_code = 422
    default_message = "The request could not be validated."


class InternalError(DomainError):
    code = "INTERNAL_ERROR"
    status_code = 500
    default_message = "An unexpected error occurred."


_STARLETTE_STATUS_CODES: dict[int, str] = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


def build_error_envelope(code: str, message: str, details: dict | None = None) -> dict:
    """Build the Section 10.8 error envelope.

    Public so that middleware sitting outside FastAPI's exception-handler
    layer (e.g. the rate limiter, which must short-circuit before routing)
    can produce the exact same response shape without raising a DomainError
    that would never be caught.
    """
    error_body: dict = {"code": code, "message": message}
    if details is not None:
        error_body["details"] = details
    return {"error": error_body, "request_id": get_request_id()}


def register_exception_handlers(app: FastAPI) -> None:
    """Register the full error-envelope chain on a FastAPI app instance."""

    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        log = logger.warning if exc.status_code < 500 else logger.error
        log(
            "request_failed",
            error_code=exc.code,
            status_code=exc.status_code,
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_envelope(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "request_validation_failed",
            path=request.url.path,
            method=request.method,
            errors=jsonable_encoder(exc.errors()),
        )
        return JSONResponse(
            status_code=422,
            content=build_error_envelope(
                "VALIDATION_FAILED",
                "The request could not be validated.",
                details={"errors": jsonable_encoder(exc.errors())},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STARLETTE_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
        logger.warning(
            "http_exception",
            status_code=exc.status_code,
            path=request.url.path,
            method=request.method,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=build_error_envelope(code, str(exc.detail) or "An error occurred."),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            path=request.url.path,
            method=request.method,
            exc_info=exc,
        )
        return JSONResponse(
            status_code=500,
            content=build_error_envelope("INTERNAL_ERROR", "An unexpected error occurred."),
        )
