"""Contract tests for GET/DELETE /api/v1/history (SDD Section 10.5, 10.6)."""

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


def _upload_one(client: TestClient) -> None:
    # /chat now requires a READY document (Phase 5), so this must be a
    # real, parseable PDF - not the fake minimal bytes used elsewhere for
    # validation-only tests. Unique body text per call so repeated calls
    # within one test (e.g. two sessions in the same test) don't collide
    # with the SHA-256 dedup check.
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "Leave Policy", fontsize=18, fontname="helv")
    page.insert_text(
        (72, 120),
        f"Employees receive twelve days of annual leave per year. {uuid.uuid4()}",
        fontsize=11,
        fontname="helv",
    )
    content = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/upload", files=[("files", ("policy.pdf", content, "application/pdf"))]
    )
    assert response.status_code == 202


def _create_session_with_turn(client: TestClient, question: str = "Q1") -> str:
    _upload_one(client)
    response = client.post("/api/v1/chat", json={"session_id": None, "question": question})
    return response.json()["session_id"]


def test_get_history_returns_turns_in_order(client: TestClient):
    session_id = _create_session_with_turn(client, "How many leaves?")
    response = client.get("/api/v1/history", params={"session_id": session_id})
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == session_id
    assert len(body["turns"]) == 2
    assert body["turns"][0]["role"] == "user"
    assert body["turns"][0]["content"] == "How many leaves?"
    assert body["turns"][1]["role"] == "assistant"


def test_get_history_unknown_session_returns_404(client: TestClient):
    response = client.get("/api/v1/history", params={"session_id": str(uuid.uuid4())})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_get_history_missing_session_id_returns_422(client: TestClient):
    response = client.get("/api/v1/history")
    assert response.status_code == 422


def test_delete_history_by_session_id(client: TestClient):
    session_id = _create_session_with_turn(client)
    response = client.delete("/api/v1/history", params={"session_id": session_id})
    assert response.status_code == 200
    body = response.json()
    assert body["sessions_cleared"] == 1
    assert body["messages_deleted"] == 2

    assert client.get("/api/v1/history", params={"session_id": session_id}).status_code == 404


def test_delete_history_all_sessions(client: TestClient):
    _create_session_with_turn(client, "Q1")
    _create_session_with_turn(client, "Q2")

    response = client.delete("/api/v1/history", params={"all": "true"})
    assert response.status_code == 200
    body = response.json()
    assert body["sessions_cleared"] == 2
    assert body["messages_deleted"] == 4


def test_delete_history_without_params_returns_422(client: TestClient):
    response = client.delete("/api/v1/history")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"
