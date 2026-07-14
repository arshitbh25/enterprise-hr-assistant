"""Contract tests for GET /api/v1/sessions.

Added alongside Phase 7 (frontend session sidebar) - see
app/api/schemas/sessions.py for why this endpoint exists.
"""

import uuid

import fitz
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_service
from tests._fakes import FakeLLMService


@pytest.fixture(autouse=True)
def fake_llm(client: TestClient) -> FakeLLMService:
    fake = FakeLLMService()
    client.app.dependency_overrides[get_llm_service] = lambda: fake
    return fake


def _create_session(client: TestClient, question: str = "Q1", headers: dict | None = None) -> str:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text(
        (72, 80),
        f"Employees receive twelve days of annual leave per year. {uuid.uuid4()}",
        fontsize=11,
        fontname="helv",
    )
    content = doc.tobytes()
    doc.close()
    upload_response = client.post(
        "/api/v1/upload",
        files=[("files", ("policy.pdf", content, "application/pdf"))],
        headers=headers,
    )
    assert upload_response.status_code == 202

    response = client.post(
        "/api/v1/chat",
        json={"session_id": None, "question": question},
        headers=headers,
    )
    return response.json()["session_id"]


def test_list_sessions_empty_by_default(client: TestClient):
    response = client.get("/api/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_sessions_returns_created_session(client: TestClient):
    session_id = _create_session(client, "How many leaves?")

    response = client.get("/api/v1/sessions")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == session_id


def test_list_sessions_orders_by_last_activity_desc(client: TestClient):
    first = _create_session(client, "Q1")
    second = _create_session(client, "Q2")

    body = client.get("/api/v1/sessions").json()
    assert [item["id"] for item in body["items"]] == [second, first]


def test_list_sessions_pagination(client: TestClient):
    for i in range(3):
        _create_session(client, f"Q{i}")

    body = client.get("/api/v1/sessions", params={"page": 1, "page_size": 2}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_list_sessions_excludes_deleted_sessions(client: TestClient):
    session_id = _create_session(client)
    client.delete("/api/v1/history", params={"session_id": session_id})

    body = client.get("/api/v1/sessions").json()
    assert body["total"] == 0


def test_list_sessions_is_scoped_to_the_requesting_user(client: TestClient):
    other_user = str(uuid.uuid4())
    _create_session(client, "Mine", headers={"X-User-Id": other_user})

    body = client.get("/api/v1/sessions").json()
    assert body["total"] == 0

    scoped_body = client.get("/api/v1/sessions", headers={"X-User-Id": other_user}).json()
    assert scoped_body["total"] == 1
