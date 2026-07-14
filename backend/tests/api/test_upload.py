"""Contract tests for POST /api/v1/upload (SDD Section 10.1)."""

from collections.abc import Callable

from fastapi.testclient import TestClient

_FAKE_PDF = b"%PDF-1.4\n%fake minimal pdf content for contract tests\n%%EOF"


def _pdf_file(name: str = "policy.pdf", content: bytes = _FAKE_PDF) -> tuple:
    return ("files", (name, content, "application/pdf"))


def test_upload_single_valid_pdf_returns_202(client: TestClient):
    response = client.post("/api/v1/upload", files=[_pdf_file()])
    assert response.status_code == 202
    body = response.json()
    assert len(body["results"]) == 1
    result = body["results"][0]
    assert result["status"] == "UPLOADED"
    assert result["document_id"]
    assert result["error"] is None
    assert body["request_id"]


def test_upload_multiple_valid_pdfs_returns_202_with_all_results(client: TestClient):
    files = [_pdf_file("a.pdf", _FAKE_PDF + b"a"), _pdf_file("b.pdf", _FAKE_PDF + b"b")]
    response = client.post("/api/v1/upload", files=files)
    assert response.status_code == 202
    body = response.json()
    assert len(body["results"]) == 2
    assert all(r["status"] == "UPLOADED" for r in body["results"])


def test_upload_non_pdf_file_is_rejected_with_415(client: TestClient):
    response = client.post(
        "/api/v1/upload", files=[("files", ("notes.txt", b"just some text", "text/plain"))]
    )
    assert response.status_code == 415
    result = response.json()["results"][0]
    assert result["status"] == "REJECTED"
    assert result["error"]["code"] == "INVALID_FILE_TYPE"


def test_upload_duplicate_content_is_rejected_with_409(client: TestClient):
    first = client.post("/api/v1/upload", files=[_pdf_file()])
    assert first.status_code == 202

    second = client.post("/api/v1/upload", files=[_pdf_file()])
    assert second.status_code == 409
    result = second.json()["results"][0]
    assert result["status"] == "REJECTED"
    assert result["error"]["code"] == "DUPLICATE_DOCUMENT"


def test_upload_oversized_file_is_rejected_with_413(make_client: Callable[..., TestClient]):
    with make_client(upload_max_file_mb=0) as client:
        response = client.post("/api/v1/upload", files=[_pdf_file()])
        assert response.status_code == 413
        result = response.json()["results"][0]
        assert result["error"]["code"] == "FILE_TOO_LARGE"


def test_upload_encrypted_pdf_marker_is_rejected_with_422(client: TestClient):
    content = b"%PDF-1.4\n/Encrypt 5 0 R\n%%EOF"
    response = client.post("/api/v1/upload", files=[_pdf_file("secure.pdf", content)])
    assert response.status_code == 422
    result = response.json()["results"][0]
    assert result["error"]["code"] == "ENCRYPTED_PDF"


def test_upload_no_files_returns_400(client: TestClient):
    response = client.post("/api/v1/upload", files=[])
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_upload_too_many_files_returns_400(make_client: Callable[..., TestClient]):
    with make_client(upload_max_files=1) as client:
        files = [_pdf_file("a.pdf", _FAKE_PDF + b"a"), _pdf_file("b.pdf", _FAKE_PDF + b"b")]
        response = client.post("/api/v1/upload", files=files)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"


def test_upload_mixed_failures_returns_generic_400(client: TestClient):
    client.post("/api/v1/upload", files=[_pdf_file()])  # seed a duplicate target

    files = [("files", ("notes.txt", b"not a pdf", "text/plain")), _pdf_file()]
    response = client.post("/api/v1/upload", files=files)
    assert response.status_code == 400
    codes = {r["error"]["code"] for r in response.json()["results"]}
    assert codes == {"INVALID_FILE_TYPE", "DUPLICATE_DOCUMENT"}
