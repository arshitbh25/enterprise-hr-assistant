"""Request-ID correlation middleware (SDD 5.3, 6.3.1, Section 3.6).

Must be the OUTERMOST middleware in the stack. Starlette's
``add_middleware`` inserts each new middleware at the front of the list,
so the middleware added *last* ends up outermost — wire this one last in
``app/main.py`` so every other middleware, every exception handler, and
every log line can rely on request_id already being bound.
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import Settings
from app.core.logging import bind_request_id, clear_request_context, get_logger

logger = get_logger(__name__)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates a correlation ID and logs one event per request."""

    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._header_name = settings.request_id_header

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get(self._header_name)
        request_id = incoming or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_request_id(request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers[self._header_name] = request_id
            logger.info(
                "request_handled",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            clear_request_context()
