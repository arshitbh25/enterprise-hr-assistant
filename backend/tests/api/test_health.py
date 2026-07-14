"""Contract tests for GET /api/v1/health (SDD Section 10.7)."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.database.session import get_db_session
from app.main import create_app
from app.services.vector_store import ChromaVectorStore


def test_health_returns_200_degraded_when_only_llm_not_configured(client: TestClient):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["api"] == "up"
    assert body["checks"]["database"] == "up"
    assert body["checks"]["vector_store"] == "up"
    assert body["checks"]["embedding_model"] == "up"
    assert body["checks"]["llm"] == "not_configured"
    assert "version" in body


def test_health_response_has_no_error_envelope(client: TestClient):
    response = client.get("/api/v1/health")
    assert "error" not in response.json()


class _BrokenDbSession:
    def execute(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated DB outage")


def test_health_returns_503_unhealthy_when_database_fails(settings: Settings):
    app = create_app(settings)
    app.dependency_overrides[get_db_session] = lambda: _BrokenDbSession()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"] == "down"


def test_health_returns_503_unhealthy_when_vector_store_down(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(ChromaVectorStore, "heartbeat", lambda self: False)

    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["checks"]["vector_store"] == "down"
    assert body["checks"]["database"] == "up"
