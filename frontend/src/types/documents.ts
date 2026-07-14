// Mirrors backend/app/api/schemas/documents.py

import type { DocumentStatus } from './enums'

export interface DocumentSummary {
  id: string
  display_name: string
  size_bytes: number
  page_count: number | null
  chunk_count: number
  status: DocumentStatus
  failure_reason: string | null
  uploaded_by: string
  created_at: string
  ready_at: string | null
}

export interface DocumentListResponse {
  items: DocumentSummary[]
  total: number
  page: number
  page_size: number
}

export interface DocumentDeleteResponse {
  document_id: string
  chunks_removed: number
}
