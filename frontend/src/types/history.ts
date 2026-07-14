// Mirrors backend/app/api/schemas/history.py

import type { Citation } from './chat'
import type { ConfidenceLevel, MessageRole } from './enums'

export interface HistoryTurn {
  role: MessageRole
  content: string
  citations: Citation[]
  confidence: ConfidenceLevel | null
  created_at: string
}

export interface HistoryResponse {
  session_id: string
  title: string | null
  turns: HistoryTurn[]
}

export interface HistoryDeleteResponse {
  sessions_cleared: number
  messages_deleted: number
}
