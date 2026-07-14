"""Schemas for GET /api/v1/health (SDD Section 10.7)."""

from typing import Literal

from pydantic import BaseModel

HealthStatus = Literal["healthy", "degraded", "unhealthy"]


class HealthChecks(BaseModel):
    api: str
    database: str
    vector_store: str
    embedding_model: str
    llm: str


class HealthResponse(BaseModel):
    status: HealthStatus
    checks: HealthChecks
    version: str
