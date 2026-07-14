"""Unit tests for app.middleware.request_id."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import get_request_id
from app.middleware.request_id import RequestIDMiddleware


def _build_app() -> FastAPI:
    settings = Settings(_env_file=None)
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware, settings=settings)

    @app.get("/echo")
    async def echo(request: Request):
        return {"request_id": request.state.request_id, "bound": get_request_id()}

    return app


def test_generates_request_id_when_absent():
    client = TestClient(_build_app())
    response = client.get("/echo")
    assert response.status_code == 200
    header_value = response.headers["X-Request-ID"]
    assert header_value
    body = response.json()
    assert body["request_id"] == header_value
    assert body["bound"] == header_value


def test_echoes_client_supplied_request_id():
    client = TestClient(_build_app())
    response = client.get("/echo", headers={"X-Request-ID": "client-supplied-123"})
    assert response.headers["X-Request-ID"] == "client-supplied-123"
    assert response.json()["request_id"] == "client-supplied-123"


def test_context_cleared_after_request():
    client = TestClient(_build_app())
    client.get("/echo")
    assert get_request_id() is None
