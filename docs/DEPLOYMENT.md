# Deployment (Railway, single-service)

Phase P9 (`docs/sdd.md` Section 13). This deploys the root `Dockerfile`
as **one** Railway service: FastAPI serves both the API and the built
React SPA, same-origin. See ADR-011 (`docs/sdd.md` Appendix B) for why
this deviates from Section 9's two-service `docker-compose` picture -
that picture is still correct for local dev, which is unaffected by any
of this.

## Prerequisites

- The image builds and runs cleanly locally first — see
  ["Local verification"](#local-verification-run-this-before-every-railway-deploy)
  below. Never skip straight to Railway on a Dockerfile change.
- A Gemini API key (`docs/threshold-calibration.md` if you're swapping
  models).

## Steps

1. **New Railway project → "Deploy from GitHub repo"**, pointing at this
   repository. Railway auto-detects the root `Dockerfile` — no
   `railway.json`/Nixpacks config needed.
2. **Attach a volume**, mount path `/data`. This is the *only* persistent
   state: SQLite DB, uploaded PDFs, and the Chroma vector index all live
   under it (Section 2 below). Without this volume, a redeploy wipes
   every document and conversation.
3. **Environment variables** — set these on the service:

   | Var | Value | Why |
   |---|---|---|
   | `DATABASE_URL` | `sqlite:////data/hr_assistant.db` | 4 slashes = absolute path under the volume |
   | `STORAGE_DIR` | `/data/storage` | original uploaded PDFs |
   | `CHROMA_DIR` | `/data/chroma` | vector index |
   | `APP_ENV` | `production` | JSON logs instead of console-pretty (`app/core/logging.py`) |
   | `LOG_LEVEL` | `INFO` | |
   | `GEMINI_API_KEY` | *(your key)* | never commit this - Railway's env var store only |
   | `GEMINI_MODEL_NAME` | `gemini-3.5-flash` | current model - re-check via the 404 troubleshooting note in `README.md` if this is ever retired |
   | `GEMINI_TIMEOUT_SECONDS` | `45` | real-call margin, see `docs/threshold-calibration.md` |
   | `GROUNDEDNESS_REJECT_THRESHOLD` | `0.10` | calibrated for the current model - **do not change without re-running `python scripts/calibrate_threshold.py --live` first** |
   | `GROUNDEDNESS_COMFORTABLE_THRESHOLD` | `0.13` | same as above |

   `CORS_ORIGINS` is **not needed** in this topology: the SPA is served
   by the same FastAPI process it calls, so every request is
   same-origin. Leave it unset (defaults to `http://localhost:5173`,
   which is simply unused in production).

   Everything else in `backend/.env.example` has a workable default —
   only override rate-limit/session/upload-limit values if you actually
   need different ones.

4. **Health check path**: `/api/v1/health`. Railway's own health check
   only needs an HTTP 200; `GET /api/v1/health` already returns 200 for
   both `"healthy"` and `"degraded"` overall status (only `"unhealthy"` -
   a real DB or vector-store outage - returns 503), so a container that's
   up but has, say, an unconfigured LLM check still passes Railway's
   readiness gate rather than getting killed in a restart loop. This is
   existing behavior in `app/api/v1/health.py`, unchanged by this phase.

5. **Deploy.** On every start, `entrypoint.sh` runs `alembic upgrade
   head` before `uvicorn` starts serving (SDD 3.7: "DB migrations run as
   a release step") - watch the deploy logs for the migration output
   before assuming the service is healthy.

## Rollback

Redeploy the previous image tag from Railway's deploy history (SDD
3.7's stated rollback strategy - no separate runbook needed, it's a
built-in platform feature).

## Local verification (run this before every Railway deploy)

From the repo root:

```bash
docker build -t hr-assistant .

docker run --rm -p 8000:8000 \
  -v hr-assistant-data:/data \
  -e DATABASE_URL=sqlite:////data/hr_assistant.db \
  -e STORAGE_DIR=/data/storage \
  -e CHROMA_DIR=/data/chroma \
  -e APP_ENV=production \
  -e GEMINI_API_KEY=<real key> \
  -e GEMINI_MODEL_NAME=gemini-3.5-flash \
  -e GROUNDEDNESS_REJECT_THRESHOLD=0.10 \
  -e GROUNDEDNESS_COMFORTABLE_THRESHOLD=0.13 \
  hr-assistant
```

Then confirm, in order:

1. Logs show `alembic upgrade head` running before uvicorn starts.
2. `curl localhost:8000/api/v1/health` → 200.
3. `http://localhost:8000/` loads the SPA in a browser; a direct hit on
   a client-side route (e.g. `http://localhost:8000/documents`) also
   loads the SPA rather than 404ing (`app/api/spa.py`'s fallback route).
4. Full round trip through the UI: upload a real PDF → wait for READY →
   ask a question in chat → get a grounded, cited answer. This is the
   only thing that actually proves the storage volume, Chroma
   persistence, and the Gemini call chain all work inside the container.
5. `docker stop` the container, `docker run` the same command again
   against the same named volume (`hr-assistant-data`) → the document
   and chat history from step 4 are still there. This is the real test
   of persistence - "didn't crash" and "actually persists across
   restarts" are different claims.

Only trust a Railway deploy after all of the above pass locally.

## Known issues (Phase 8 backlog)

Found during Phase P9's local Docker verification (2026-07-17) and
carried into Phase P8's (`docs/sdd.md` Section 13) triage as top
priority, alongside two already-known items:

- **`GET /api/v1/history` always returns `citations: []`** - hardcoded
  in `app/api/v1/history.py` (`HistoryTurn(..., citations=[], ...)`)
  rather than the actual persisted citations for that turn. `POST
  /chat`'s response has real citations; history replay does not.
- **Double disclaimer** - the "HR remains the final authority" line
  appears twice in some responses.
- **Footer text bleeding into citation snippets** - PDF footer content
  leaking into the extracted `snippet` field on some citations.

## Out of scope for this phase

CI/CD (Phase 8, tracked separately), custom domains, migrating off
SQLite to Postgres.
