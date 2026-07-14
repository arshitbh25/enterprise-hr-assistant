"""Unit tests for app.middleware.auth."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.middleware.auth import AuthStubMiddleware


def _build_app() -> tuple[FastAPI, Settings]:
    settings = Settings(_env_file=None)
    app = FastAPI()
    app.add_middleware(AuthStubMiddleware, settings=settings)

    @app.get("/whoami")
    async def whoami(request: Request):
        return {"user_id": request.state.user_id, "tenant_id": request.state.tenant_id}

    return app, settings


def test_defaults_to_seeded_identity_when_no_header():
    app, settings = _build_app()
    client = TestClient(app)
    body = client.get("/whoami").json()
    assert body["user_id"] == settings.default_user_id
    assert body["tenant_id"] == settings.default_tenant_id


def test_uses_supplied_user_id_header():
    app, settings = _build_app()
    client = TestClient(app)
    body = client.get("/whoami", headers={"X-User-Id": "custom-user-42"}).json()
    assert body["user_id"] == "custom-user-42"
    assert body["tenant_id"] == settings.default_tenant_id


def test_never_rejects_request_regardless_of_header():
    app, _ = _build_app()
    client = TestClient(app)
    response = client.get("/whoami", headers={"X-User-Id": "anything-goes"})
    assert response.status_code == 200
