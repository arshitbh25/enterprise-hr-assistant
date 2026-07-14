// User-facing copy for every code in the Section 10.8 error catalogue,
// plus the generic HTTP/network fallbacks. Deliberately independent of
// whatever `message` the backend sent - the backend's message is a valid
// fallback (see ApiError.friendlyMessage in apiClient.ts) but this map is
// the single place UI copy is tuned, and it's the only source of truth
// when there's no backend message at all (NETWORK_ERROR).

import type { ErrorCode } from '../types'

export const ERROR_MESSAGES: Partial<Record<ErrorCode, string>> = {
  INVALID_FILE_TYPE: 'Only PDF files are accepted.',
  FILE_TOO_LARGE: 'That file is too large to upload.',
  ENCRYPTED_PDF: "Password-protected PDFs can't be processed. Please upload an unprotected copy.",
  CORRUPT_PDF: "That file couldn't be read — it may be corrupt or empty.",
  PDF_TOO_MANY_PAGES: 'That PDF has too many pages to process.',
  PDF_PROCESSING_TIMEOUT: 'That PDF took too long to process. Please try again.',
  DUPLICATE_DOCUMENT: 'This document has already been uploaded.',
  DOCUMENT_NOT_FOUND: 'That document could not be found. It may have already been deleted.',
  DOCUMENT_PROCESSING: "This document is still being processed — try again once it's ready.",
  NO_DOCUMENTS_INDEXED: 'No HR policy documents have been uploaded yet. Ask HR to upload one first.',
  SESSION_NOT_FOUND: 'That conversation could not be found. It may have been deleted.',
  INVALID_QUESTION: 'Please enter a question (up to 2,000 characters).',
  RATE_LIMITED: "You're sending messages too quickly. Please wait a moment and try again.",
  LLM_QUOTA_EXCEEDED: 'The assistant is busy right now. Please try again in a moment.',
  LLM_UNAVAILABLE: 'The assistant is temporarily unavailable. Please try again shortly.',
  GENERATION_TIMEOUT: 'Generating the answer took too long. Please try again.',
  VECTOR_STORE_UNAVAILABLE: 'The document search service is temporarily unavailable.',
  VALIDATION_FAILED: "That request wasn't valid. Please check your input and try again.",
  INTERNAL_ERROR: 'Something went wrong on our end. Please try again.',
  UNAUTHENTICATED: 'You need to sign in to do that.',
  FORBIDDEN: "You don't have permission to do that.",
  NOT_FOUND: 'That resource could not be found.',
  METHOD_NOT_ALLOWED: "That action isn't supported.",
  HTTP_ERROR: 'Something went wrong. Please try again.',
  NETWORK_ERROR: "Couldn't reach the server. Check your connection and try again.",
}

export function friendlyMessageFor(code: string, fallback: string): string {
  return ERROR_MESSAGES[code as ErrorCode] ?? fallback
}
