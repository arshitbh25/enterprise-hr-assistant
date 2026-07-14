"""Unit tests for app.middleware.rate_limit."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.middleware.rate_limit import RateLimitMiddleware


def _build_app(limit: int = 3, window_seconds: int = 60) -> FastAPI:
    settings = Settings(
        _env_file=None,
        rate_limit_per_minute=limit,
        rate_limit_window_seconds=window_seconds,
    )
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, settings=settings)

    @app.get("/ping")
    async def ping():
        return {"pong": True}

    return app


def test_allows_requests_under_the_limit():
    client = TestClient(_build_app(limit=3))
    for _ in range(3):
        assert client.get("/ping").status_code == 200


def test_blocks_requests_over_the_limit_with_error_envelope():
    client = TestClient(_build_app(limit=2))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    response = client.get("/ping")
    assert response.status_code == 429
    body = response.json()
    assert body["error"]["code"] == "RATE_LIMITED"
    assert "Retry-After" in response.headers


def test_window_reset_allows_requests_again(monkeypatch):
    fake_time = {"now": 1000.0}
    monkeypatch.setattr("app.middleware.rate_limit.time.monotonic", lambda: fake_time["now"])

    client = TestClient(_build_app(limit=1, window_seconds=10))
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429

    fake_time["now"] += 11
    assert client.get("/ping").status_code == 200
