"""Contract tests for GET/DELETE /api/v1/documents (SDD Section 10.3, 10.4).

Ingestion (Module 4) runs as a FastAPI BackgroundTask, and Starlette's
TestClient executes background tasks synchronously before a request
call returns - so by the time `client.post("/upload", ...)` returns,
the document has already reached its terminal status (READY or FAILED).
These tests exercise that real end-to-end behavior rather than mocking
the pipeline out.
"""

import uuid
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.constants import DocumentStatus
from app.database.models import Document
from app.database.session import get_session_factory
from app.services.vector_store import ChromaVectorStore

_FAKE_PDF = b"%PDF-1.4\n%fake minimal pdf content for contract tests\n%%EOF"


def _real_pdf(text: str = "Employees receive twelve days of annual leave.") -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), text, fontsize=11, fontname="helv")
    content = doc.tobytes()
    doc.close()
    return content


def _upload(client: TestClient, content: bytes, name: str = "policy.pdf") -> str:
    response = client.post("/api/v1/upload", files=[("files", (name, content, "application/pdf"))])
    assert response.status_code == 202
    return response.json()["results"][0]["document_id"]


def test_list_documents_empty_by_default(client: TestClient):
    response = client.get("/api/v1/documents")
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_upload_of_real_pdf_reaches_ready_with_chunks(client: TestClient):
    _upload(client, _real_pdf())

    body = client.get("/api/v1/documents").json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["status"] == "READY"
    assert item["chunk_count"] > 0
    assert item["page_count"] == 1
    assert item["failure_reason"] is None


def test_upload_of_unparsable_pdf_ends_in_failed_with_reason(client: TestClient):
    _upload(client, _FAKE_PDF)

    body = client.get("/api/v1/documents").json()
    item = body["items"][0]
    assert item["status"] == "FAILED"
    assert item["failure_reason"]


def test_list_documents_pagination(client: TestClient):
    for i in range(3):
        _upload(client, _real_pdf(f"Unique policy text number {i}."))

    body = client.get("/api/v1/documents", params={"page": 1, "page_size": 2}).json()
    assert body["total"] == 3
    assert len(body["items"]) == 2


def test_list_documents_filters_by_status(client: TestClient):
    _upload(client, _real_pdf())

    body = client.get("/api/v1/documents", params={"status": "FAILED"}).json()
    assert body["total"] == 0


def test_delete_ready_document_removes_it_and_its_chunks(client: TestClient):
    document_id = _upload(client, _real_pdf())

    response = client.delete(f"/api/v1/documents/{document_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["document_id"] == document_id
    assert body["chunks_removed"] > 0

    assert client.get("/api/v1/documents").json()["total"] == 0


def test_delete_document_removes_all_its_vectors(client: TestClient, settings: Settings):
    document_id = _upload(client, _real_pdf())
    tenant_id = uuid.UUID(settings.default_tenant_id)
    store = ChromaVectorStore(settings)

    probe_embedding = [1.0] + [0.0] * 383
    before = store.query(tenant_id=tenant_id, query_embedding=probe_embedding, top_k=5)
    assert any(hit.document_id == uuid.UUID(document_id) for hit in before)

    client.delete(f"/api/v1/documents/{document_id}")

    after = store.query(tenant_id=tenant_id, query_embedding=probe_embedding, top_k=5)
    assert all(hit.document_id != uuid.UUID(document_id) for hit in after)


def test_delete_document_removes_the_stored_file(client: TestClient, settings: Settings):
    document_id = _upload(client, _real_pdf())
    stored_files = list(Path(settings.storage_dir).rglob("*.pdf"))
    assert len(stored_files) == 1
    assert stored_files[0].exists()

    client.delete(f"/api/v1/documents/{document_id}")

    assert not stored_files[0].exists()


def test_delete_unknown_document_returns_404(client: TestClient):
    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


def test_delete_mid_ingestion_document_returns_409(client: TestClient):
    document_id = _upload(client, _real_pdf())

    # Ingestion already ran to completion under TestClient; simulate
    # "still processing" by rewinding the persisted status directly.
    session = get_session_factory()()
    try:
        document = session.get(Document, uuid.UUID(document_id))
        document.status = DocumentStatus.CHUNKING
        session.commit()
    finally:
        session.close()

    response = client.delete(f"/api/v1/documents/{document_id}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DOCUMENT_PROCESSING"
