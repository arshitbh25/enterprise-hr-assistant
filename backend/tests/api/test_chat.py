"""Contract tests for POST /api/v1/chat (SDD Section 10.2).

FakeLLMService (tests/_fakes.py) is injected via app.dependency_overrides
so Gemini is never actually called; retrieval, ranking, prompt building,
and citation processing all run for real against a real
uploaded-and-ingested fixture PDF (Starlette's TestClient runs
background tasks - ingestion - synchronously before a request returns,
same as the upload/documents tests).
"""

import uuid

import fitz
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_llm_service
from app.core.exceptions import LlmUnavailableError
from tests._fakes import FakeLLMService

_FAKE_PDF = b"%PDF-1.4\n%fake minimal pdf content for contract tests\n%%EOF"


def _real_pdf(body_text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 80), "Leave Policy", fontsize=18, fontname="helv")
    page.insert_text((72, 120), body_text, fontsize=11, fontname="helv")
    content = doc.tobytes()
    doc.close()
    return content


def _upload_real_policy(client: TestClient) -> None:
    content = _real_pdf(
        "Employees are entitled to twelve days of casual leave per calendar year. "
        "Casual leave can be availed for personal reasons with prior manager "
        "approval. " * 5
    )
    response = client.post(
        "/api/v1/upload", files=[("files", ("policy.pdf", content, "application/pdf"))]
    )
    assert response.status_code == 202


def _upload_fake_pdf(client: TestClient) -> None:
    response = client.post(
        "/api/v1/upload", files=[("files", ("policy.pdf", _FAKE_PDF, "application/pdf"))]
    )
    assert response.status_code == 202


@pytest.fixture(autouse=True)
def fake_llm(client: TestClient) -> FakeLLMService:
    fake = FakeLLMService()
    client.app.dependency_overrides[get_llm_service] = lambda: fake
    return fake


def test_chat_without_documents_returns_409(client: TestClient):
    response = client.post(
        "/api/v1/chat", json={"session_id": None, "question": "How many leaves?"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DOCUMENTS_INDEXED"


def test_chat_with_only_failed_documents_returns_409(client: TestClient):
    _upload_fake_pdf(client)  # unparsable -> ends FAILED, never reaches READY

    response = client.post(
        "/api/v1/chat", json={"session_id": None, "question": "How many leaves?"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "NO_DOCUMENTS_INDEXED"


def test_chat_answerable_question_returns_citations(client: TestClient):
    _upload_real_policy(client)

    response = client.post(
        "/api/v1/chat",
        json={"session_id": None, "question": "How many casual leaves do I get?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["not_found"] is False
    assert body["confidence"] in ("high", "low")
    assert len(body["citations"]) > 0
    assert body["citations"][0]["document_name"] == "policy.pdf"
    assert "HR remains the final authority" in body["answer"]
    assert body["session_id"]
    assert body["message_id"]


def test_chat_short_circuits_before_llm_when_ranking_finds_nothing(
    client: TestClient, fake_llm: FakeLLMService, monkeypatch: pytest.MonkeyPatch
):
    # A single-chunk, single-topic fixture doesn't reliably exercise the
    # real similarity threshold (measured directly: with only one chunk
    # in the whole index, BGE's baseline similarity floor to *anything*
    # sits around 0.36-0.46, always above the 0.35 default threshold -
    # real threshold discrimination needs the multi-topic golden-set
    # fixture, tests/evaluation/test_golden_set.py). This test instead
    # verifies the wiring itself: when ranking finds nothing, /chat must
    # never call the LLM. The question is deliberately ambiguous rather
    # than off-topic (no "capital of"/"boiling point"/etc. pattern) so it
    # reaches Context Ranking - Query Understanding's own off-topic
    # short-circuit (which never touches ranking or the LLM either) is
    # covered separately.
    _upload_real_policy(client)
    monkeypatch.setattr(
        "app.agents.context_ranking.ranking.rank_chunks", lambda *args, **kwargs: []
    )

    response = client.post(
        "/api/v1/chat",
        json={
            "session_id": None,
            "question": "What is the disaster recovery procedure for the payroll system?",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["not_found"] is True
    assert body["confidence"] == "not_found"
    assert body["citations"] == []
    assert "contact HR" in body["answer"]
    assert fake_llm.calls == []


def test_chat_empty_question_returns_422(client: TestClient):
    _upload_real_policy(client)
    response = client.post("/api/v1/chat", json={"session_id": None, "question": "   "})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_QUESTION"


def test_chat_reuses_existing_session(client: TestClient):
    _upload_real_policy(client)
    first = client.post(
        "/api/v1/chat", json={"session_id": None, "question": "How many casual leaves?"}
    )
    session_id = first.json()["session_id"]

    second = client.post(
        "/api/v1/chat", json={"session_id": session_id, "question": "How many casual leaves?"}
    )
    assert second.status_code == 200
    assert second.json()["session_id"] == session_id


def test_chat_unknown_session_returns_404(client: TestClient):
    _upload_real_policy(client)
    response = client.post(
        "/api/v1/chat", json={"session_id": str(uuid.uuid4()), "question": "Q"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "SESSION_NOT_FOUND"


def test_chat_llm_failure_maps_to_503(client: TestClient, fake_llm: FakeLLMService):
    _upload_real_policy(client)
    fake_llm.raise_error = LlmUnavailableError()

    response = client.post(
        "/api/v1/chat", json={"session_id": None, "question": "How many casual leaves?"}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


def test_chat_off_topic_question_short_circuits_without_calling_llm(
    client: TestClient, fake_llm: FakeLLMService
):
    """Module 7: Query Understanding Agent's scope short-circuit (FR-Q07),
    now wired end-to-end through the orchestrator - never reaches
    retrieval or the LLM."""
    _upload_real_policy(client)

    response = client.post(
        "/api/v1/chat",
        json={"session_id": None, "question": "What is the capital of France?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["not_found"] is True
    assert "only help with questions about HR policy" in body["answer"]
    assert fake_llm.calls == []


def test_chat_greeting_short_circuits_without_calling_llm(
    client: TestClient, fake_llm: FakeLLMService
):
    _upload_real_policy(client)

    response = client.post("/api/v1/chat", json={"session_id": None, "question": "Hello!"})

    assert response.status_code == 200
    body = response.json()
    assert body["not_found"] is True
    assert "HR policy assistant" in body["answer"]
    assert fake_llm.calls == []


def test_chat_follow_up_question_is_rewritten_using_conversation_history(
    client: TestClient, fake_llm: FakeLLMService
):
    """Module 7: proves Memory + Query Understanding are actually wired
    into /chat, not just unit-tested in isolation - a follow-up on the
    second turn of a session triggers a rewrite call carrying the first
    turn's history, and the resulting standalone query is what reaches
    retrieval/prompt construction (visible as <history> in the final
    answer-generation prompt)."""
    _upload_real_policy(client)
    rewritten_query = "What is the casual leave policy for interns?"

    def _respond(prompt: str) -> str:
        if "Follow-up question:" in prompt:
            return rewritten_query
        if 'id="S1"' in prompt:
            return "Employees get twelve days of leave. [S1]"
        return "NOT_FOUND"

    fake_llm._respond = _respond  # test double: swap the canned responder mid-test

    first = client.post(
        "/api/v1/chat",
        json={"session_id": None, "question": "How many casual leaves do I get?"},
    )
    session_id = first.json()["session_id"]
    fake_llm.calls.clear()

    second = client.post(
        "/api/v1/chat",
        json={"session_id": session_id, "question": "What about for interns?"},
    )

    assert second.status_code == 200
    # First call is the rewrite, second is the grounded-answer generation.
    assert len(fake_llm.calls) == 2
    assert "Follow-up question:" in fake_llm.calls[0]
    assert "How many casual leaves do I get?" in fake_llm.calls[0]
    answer_prompt = fake_llm.calls[1]
    assert "<history>" in answer_prompt
    assert "Q: How many casual leaves do I get?" in answer_prompt
    assert f"<question>\n{rewritten_query}\n</question>" in answer_prompt


def test_chat_ranking_short_circuit_still_persists_the_turn(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """SDD §6.3.9 / MemoryWriteAgent's own docstring: even a turn that
    short-circuits before ever reaching the LLM must still be persisted
    with its refusal answer - a correct refusal is a successful,
    recorded turn (FR-Q03), not a dropped one. Verified end-to-end via
    the public API (POST /chat then GET /history), not just at the
    MemoryWriteAgent unit-test level."""
    _upload_real_policy(client)
    monkeypatch.setattr(
        "app.agents.context_ranking.ranking.rank_chunks", lambda *args, **kwargs: []
    )

    chat_response = client.post(
        "/api/v1/chat",
        json={
            "session_id": None,
            "question": "What is the disaster recovery procedure for the payroll system?",
        },
    )
    assert chat_response.status_code == 200
    session_id = chat_response.json()["session_id"]

    history_response = client.get("/api/v1/history", params={"session_id": session_id})

    assert history_response.status_code == 200
    turns = history_response.json()["turns"]
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "What is the disaster recovery procedure for the payroll system?"
    assert turns[1]["role"] == "assistant"
    assert "contact HR" in turns[1]["content"]
    assert turns[1]["confidence"] == "not_found"


def test_chat_off_topic_short_circuit_still_persists_the_turn(client: TestClient):
    _upload_real_policy(client)

    chat_response = client.post(
        "/api/v1/chat",
        json={"session_id": None, "question": "What is the capital of France?"},
    )
    assert chat_response.status_code == 200
    session_id = chat_response.json()["session_id"]

    history_response = client.get("/api/v1/history", params={"session_id": session_id})

    assert history_response.status_code == 200
    turns = history_response.json()["turns"]
    assert len(turns) == 2
    assert turns[0]["role"] == "user"
    assert turns[0]["content"] == "What is the capital of France?"
    assert turns[1]["role"] == "assistant"
    assert "only help with questions about HR policy" in turns[1]["content"]
    assert turns[1]["confidence"] == "not_found"
