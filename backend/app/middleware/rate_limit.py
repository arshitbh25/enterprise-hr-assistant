"""In-memory per-client-IP rate limiter (SDD 11.6, edge tier).

Fixed-window counter: cheap and easy to reason about, sufficient for a
single-process v1 deployment. Known simplifications, both acceptable for
this phase: a process restart resets all counts, multiple worker
processes would each keep independent counts, and the bucket dict is
never evicted for IPs that stop sending traffic. A shared, TTL-evicting
(Redis-backed) limiter is Phase-12 territory (SDD Section 12) once
horizontal scaling and the Gemini provider-side quota governor matter.

Must run *inside* RequestIDMiddleware (i.e. added to the app before it,
per the ordering note in request_id.py) so a 429 response still carries
a correlated request_id in its envelope and log line.
"""

import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import Settings
from app.core.exceptions import build_error_envelope
from app.core.logging import get_logger

logger = get_logger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._limit = settings.rate_limit_per_minute
        self._window_seconds = settings.rate_limit_window_seconds
        self._buckets: dict[str, tuple[float, int]] = {}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        client_key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start, count = self._buckets.get(client_key, (now, 0))

        if now - window_start >= self._window_seconds:
            window_start, count = now, 0

        count += 1
        self._buckets[client_key] = (window_start, count)

        if count > self._limit:
            retry_after = max(1, int(self._window_seconds - (now - window_start)))
            logger.warning(
                "rate_limit_exceeded",
                client=client_key,
                count=count,
                limit=self._limit,
            )
            return JSONResponse(
                status_code=429,
                content=build_error_envelope(
                    "RATE_LIMITED",
                    "Too many requests. Please slow down and try again shortly.",
                ),
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)
