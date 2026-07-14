// UI-only composed state - not a mirror of a backend schema (see other
// files in this folder), so it lives here rather than being confused
// for one. A ChatMessage is what the Chat page renders per turn; it's
// assembled from ChatResponse (live turns) or HistoryTurn (Module 5).

import type { Citation } from './chat'
import type { ConfidenceLevel, MessageRole } from './enums'

export interface ChatMessage {
  id: string
  role: MessageRole
  content: string
  citations: Citation[]
  confidence: ConfidenceLevel | null
  notFound: boolean
  createdAt: string
}
