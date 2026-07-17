"""Tests for app/api/spa.py: SPA static serving (ADR-011, Railway deploy)."""

from collections.abc import Callable
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def dist_dir(tmp_path: Path) -> Path:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>index</html>")
    (dist / "assets" / "x.js").write_text("console.log('x')")
    (dist / "favicon.svg").write_text("<svg></svg>")
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    return dist


@pytest.fixture()
def spa_client(make_client: Callable[..., TestClient], dist_dir: Path) -> TestClient:
    with make_client(frontend_dist_dir=str(dist_dir)) as client:
        yield client


def test_root_serves_index_html(spa_client: TestClient):
    response = spa_client.get("/")
    assert response.status_code == 200
    assert "index" in response.text


def test_assets_are_served(spa_client: TestClient):
    response = spa_client.get("/assets/x.js")
    assert response.status_code == 200
    assert "console.log" in response.text


def test_real_root_file_is_served(spa_client: TestClient):
    response = spa_client.get("/favicon.svg")
    assert response.status_code == 200
    assert "svg" in response.text


def test_client_side_route_falls_back_to_index_html(spa_client: TestClient):
    response = spa_client.get("/documents")
    assert response.status_code == 200
    assert "index" in response.text


def test_path_traversal_cannot_escape_dist_dir(spa_client: TestClient):
    # %2e%2e survives client-side URL normalization (unlike a literal
    # "..", which httpx/RFC 3986 would collapse before the request is
    # even sent) - Starlette decodes it server-side into "..", exactly
    # the case mount_spa()'s is_relative_to() guard exists for.
    response = spa_client.get("/%2e%2e/secret.txt")
    assert response.status_code == 200
    assert "TOP-SECRET" not in response.text
    assert "index" in response.text


def test_health_endpoint_still_handled_by_the_real_router(spa_client: TestClient):
    response = spa_client.get("/api/v1/health")
    assert response.status_code in (200, 503)
    assert "checks" in response.json()


def test_spa_not_mounted_when_frontend_dist_dir_unset(client: TestClient):
    response = client.get("/documents")
    assert response.status_code == 404
