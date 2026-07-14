// Mirrors backend/app/api/schemas/sessions.py (added alongside this
// phase - see docs/sdd.md Section 10.3a for why this endpoint exists).

export interface SessionSummary {
  id: string
  title: string | null
  created_at: string
  last_activity_at: string
}

export interface SessionListResponse {
  items: SessionSummary[]
  total: number
  page: number
  page_size: number
}
