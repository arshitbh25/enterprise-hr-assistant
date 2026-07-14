// Mirrors backend/app/core/exceptions.py: build_error_envelope() + the
// Section 10.8 error code catalogue, plus the generic Starlette-level
// codes (_STARLETTE_STATUS_CODES) that can also reach the client.

export type ErrorCode =
  | 'INVALID_FILE_TYPE'
  | 'FILE_TOO_LARGE'
  | 'ENCRYPTED_PDF'
  | 'CORRUPT_PDF'
  | 'PDF_TOO_MANY_PAGES'
  | 'PDF_PROCESSING_TIMEOUT'
  | 'DUPLICATE_DOCUMENT'
  | 'DOCUMENT_NOT_FOUND'
  | 'DOCUMENT_PROCESSING'
  | 'NO_DOCUMENTS_INDEXED'
  | 'SESSION_NOT_FOUND'
  | 'INVALID_QUESTION'
  | 'RATE_LIMITED'
  | 'LLM_QUOTA_EXCEEDED'
  | 'LLM_UNAVAILABLE'
  | 'GENERATION_TIMEOUT'
  | 'VECTOR_STORE_UNAVAILABLE'
  | 'VALIDATION_FAILED'
  | 'INTERNAL_ERROR'
  // Generic Starlette-level fallbacks (app/core/exceptions.py _STARLETTE_STATUS_CODES)
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'METHOD_NOT_ALLOWED'
  | 'HTTP_ERROR'
  // Client-side only: no HTTP response was received at all (offline, DNS
  // failure, backend not running) - the backend never gets a chance to
  // produce an envelope for this case.
  | 'NETWORK_ERROR'

export interface ErrorBody {
  code: string
  message: string
  details?: Record<string, unknown>
}

export interface ErrorEnvelope {
  error: ErrorBody
  request_id: string | null
}
