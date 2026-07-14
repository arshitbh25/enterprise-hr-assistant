// Mirrors backend/app/core/constants.py enums used in API schemas.

export type DocumentStatus =
  | 'UPLOADED'
  | 'PARSING'
  | 'CHUNKING'
  | 'EMBEDDING'
  | 'READY'
  | 'FAILED'

export const NON_TERMINAL_DOCUMENT_STATUSES: readonly DocumentStatus[] = [
  'UPLOADED',
  'PARSING',
  'CHUNKING',
  'EMBEDDING',
]

export const MID_INGESTION_DOCUMENT_STATUSES: readonly DocumentStatus[] = [
  'PARSING',
  'CHUNKING',
  'EMBEDDING',
]

export type ConfidenceLevel = 'high' | 'low' | 'not_found'

export type MessageRole = 'user' | 'assistant'
