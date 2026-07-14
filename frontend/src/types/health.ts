// Mirrors backend/app/api/schemas/health.py

export type HealthStatus = 'healthy' | 'degraded' | 'unhealthy'

export interface HealthChecks {
  api: string
  database: string
  vector_store: string
  embedding_model: string
  llm: string
}

export interface HealthResponse {
  status: HealthStatus
  checks: HealthChecks
  version: string
}
