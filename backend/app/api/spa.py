"""Serves the built frontend SPA from the same FastAPI process (ADR-011).

Only mounted in the Railway single-service deployment image (see
Dockerfile), where `settings.frontend_dist_dir` points at the built
`frontend/dist/`. Local dev and tests never set that field, so
`mount_spa()` is never called outside the production container - the
Vite dev server (see `frontend/vite.config.ts`'s `/api` proxy) still
owns local frontend serving.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_spa(app: FastAPI, dist_dir: Path) -> None:
    """Mount the SPA's static assets and a client-side-routing fallback.

    Registered last, after every `/api/v1/*` router, so those routes are
    matched first and this catch-all only ever sees requests that aren't
    API calls.
    """
    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="spa-assets")

    dist_dir = dist_dir.resolve()
    index_path = dist_dir / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        # Resolve + is_relative_to guards against "../" path traversal
        # escaping dist_dir via a crafted full_path.
        candidate = (dist_dir / full_path).resolve()
        if full_path and candidate.is_relative_to(dist_dir) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_path)
