"""Tests for app/database/seed_demo.py: demo-document startup seeding
(ADR-012, Hugging Face Spaces ephemeral storage)."""

from collections.abc import Callable

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_seed_demo_document_creates_one_ready_document(make_client: Callable[..., TestClient]):
    with make_client(seed_demo_document=True) as client:
        body = client.get("/api/v1/documents").json()

    assert body["total"] == 1
    assert body["items"][0]["status"] == "READY"
    assert body["items"][0]["display_name"] == "Acme_Corp_HR_Policy_Handbook_2026.pdf"


def test_seed_demo_document_flag_off_seeds_nothing(client: TestClient):
    body = client.get("/api/v1/documents").json()
    assert body["total"] == 0


def test_seed_demo_document_is_idempotent_across_restarts(
    make_settings: Callable[..., Settings],
):
    settings = make_settings(seed_demo_document=True)

    with TestClient(create_app(settings)) as first_client:
        first = first_client.get("/api/v1/documents").json()
    assert first["total"] == 1
    seeded_id = first["items"][0]["id"]

    # A fresh app/lifespan against the *same* Settings (same tmp SQLite
    # file + storage dir) simulates a container restart against the same
    # (in this case ephemeral-but-not-yet-reset) filesystem.
    with TestClient(create_app(settings)) as second_client:
        second = second_client.get("/api/v1/documents").json()

    assert second["total"] == 1
    assert second["items"][0]["id"] == seeded_id
