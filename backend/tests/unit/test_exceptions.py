"""Unit tests for app.core.exceptions."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.exceptions import DocumentNotFoundError, DomainError, register_exception_handlers


def _build_test_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    class Body(BaseModel):
        name: str

    @app.get("/boom-domain")
    async def boom_domain():
        raise DocumentNotFoundError(details={"document_id": "abc-123"})

    @app.get("/boom-generic")
    async def boom_generic():
        raise RuntimeError("kaboom")

    @app.post("/validate")
    async def validate(body: Body):
        return {"name": body.name}

    return app


def test_domain_error_envelope():
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    response = client.get("/boom-domain")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "DOCUMENT_NOT_FOUND"
    assert body["error"]["details"] == {"document_id": "abc-123"}
    assert "request_id" in body


def test_unhandled_exception_returns_generic_500_without_leaking_details():
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    response = client.get("/boom-generic")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert "kaboom" not in response.text


def test_request_validation_error_returns_422_with_details():
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    response = client.post("/validate", json={"wrong_field": 1})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert "errors" in body["error"]["details"]


def test_not_found_route_returns_envelope():
    client = TestClient(_build_test_app(), raise_server_exceptions=False)
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"


def test_all_catalogue_codes_have_unique_status_and_code():
    subclasses = DomainError.__subclasses__()
    codes = [cls.code for cls in subclasses]
    assert len(codes) == len(set(codes)), "duplicate error codes detected"
    expected_codes = {
        "INVALID_FILE_TYPE",
        "FILE_TOO_LARGE",
        "ENCRYPTED_PDF",
        "CORRUPT_PDF",
        "PDF_TOO_MANY_PAGES",
        "PDF_PROCESSING_TIMEOUT",
        "DUPLICATE_DOCUMENT",
        "DOCUMENT_NOT_FOUND",
        "DOCUMENT_PROCESSING",
        "NO_DOCUMENTS_INDEXED",
        "SESSION_NOT_FOUND",
        "INVALID_QUESTION",
        "RATE_LIMITED",
        "LLM_QUOTA_EXCEEDED",
        "LLM_UNAVAILABLE",
        "GENERATION_TIMEOUT",
        "VECTOR_STORE_UNAVAILABLE",
        "VALIDATION_FAILED",
        "INTERNAL_ERROR",
    }
    assert set(codes) == expected_codes
