"""Permissive auth stub (SDD 5.3, 11).

Attaches an identity to every request so downstream code (repositories,
routes) always reads ``request.state.user_id`` / ``request.state.tenant_id``
and never a header directly. This is the seam a real JWT/OIDC/SSO
middleware drops into later without touching any caller — v1 is
single-tenant, so tenant_id is always the seeded default; user_id is
whatever the client claims via header, or the seeded default admin.
Never rejects a request (no real verification happens yet).
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.core.config import Settings


class AuthStubMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        super().__init__(app)
        self._header_name = settings.auth_header_name
        self._default_user_id = settings.default_user_id
        self._default_tenant_id = settings.default_tenant_id

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.user_id = request.headers.get(self._header_name) or self._default_user_id
        request.state.tenant_id = self._default_tenant_id
        return await call_next(request)
