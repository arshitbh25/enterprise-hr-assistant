// Mirrors backend/app/api/schemas/chat.py

import type { ConfidenceLevel } from './enums'

export interface ChatRequest {
  session_id: string | null
  question: string
}

export interface Citation {
  document_name: string
  pages: number[]
  section: string | null
  snippet: string
}

export interface ChatResponse {
  session_id: string
  message_id: string
  answer: string
  confidence: ConfidenceLevel
  citations: Citation[]
  not_found: boolean
  latency_ms: number
  request_id: string | null
}
