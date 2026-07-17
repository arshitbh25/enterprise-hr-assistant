# Deployment

Phase P9 (`docs/sdd.md` Section 13). Root `Dockerfile`, one container:
FastAPI serves both the API and the built React SPA, same-origin
(`app/api/spa.py`).

**Current target: Hugging Face Spaces** (Docker SDK, free CPU tier —
ADR-012, `docs/sdd.md` Appendix B). Railway (ADR-011) was the original
plan and its runbook is kept below for reference / as a documented
alternative, but it is not the active deployment.

## Hugging Face Spaces (current target)

Spaces' free CPU tier gives 16GB RAM, comfortably fitting this image
(torch + transformers + chromadb) — a 512MB Render free tier could not
run it at all. The trade-off: **ephemeral storage**. The container
filesystem resets on every Space restart/rebuild, so there is no
mounted-volume equivalent to Railway's `/data`. This is mitigated, not
solved: `app/database/seed_demo.py` re-ingests a bundled sample PDF
(`backend/seed_data/Acme_Corp_HR_Policy_Handbook_2026.pdf`) on every cold
start if the tenant has no documents yet, so the deployed demo never
boots into an empty state — but anything a visitor uploads live will not
survive a restart. This is a portfolio/demo deployment, not a production
one.

### Prerequisites

- The image builds and runs cleanly locally first (same
  ["Local verification"](#local-verification-spaces-style-defaults)
  as any other Dockerfile change).
- A Gemini API key.

### Steps

1. **Create a new Space** at huggingface.co/new-space: pick **Docker**
   as the SDK. This gives you a Space with its own git remote,
   `https://huggingface.co/spaces/<your-username>/<space-name>` —
   a separate repository from this GitHub repo, not a fork or mirror.

2. **Push this repo's code to the Space's git remote**, with one extra
   step: Spaces reads the front-matter (`title`/`emoji`/`sdk`/
   `app_port`/...) from whatever file is literally named `README.md` at
   the pushed branch's root. This repo's own `README.md` is the curated
   GitHub front page and has no such front-matter, so swap in
   `README_SPACE.md` (the versioned source of the Space's metadata +
   demo-facing blurb) for that one file on the push:
   ```bash
   git remote add space https://huggingface.co/spaces/<your-username>/<space-name>
   git checkout -b space-deploy
   cp README_SPACE.md README.md
   git add README.md
   git commit -m "Space README front-matter"
   git push space space-deploy:main
   git checkout main   # back to the real branch; leave README.md as-is here
   ```
   (Alternative: use the Space's "Files" web UI to upload `README_SPACE.md`
   renamed to `README.md`, and upload/sync the rest of the code the same
   way, if you'd rather not manage a second git remote.)

3. **Secrets vs. Variables** (Space Settings → "Variables and secrets" —
   Spaces' own terminology, distinct from Railway's flat env var list):

   | Type | Var | Value |
   |---|---|---|
   | Secret | `GEMINI_API_KEY` | *(your key)* — never commit this |
   | Variable | `GEMINI_MODEL_NAME` | `gemini-3.5-flash` |
   | Variable | `GEMINI_TIMEOUT_SECONDS` | `45` |
   | Variable | `GROUNDEDNESS_REJECT_THRESHOLD` | `0.10` — do not change without re-running `python scripts/calibrate_threshold.py --live` first |
   | Variable | `GROUNDEDNESS_COMFORTABLE_THRESHOLD` | `0.13` — same as above |
   | Variable | `APP_ENV` | `production` |
   | Variable | `SEED_DEMO_DOCUMENT` | `true` — this is what makes the demo self-healing on Spaces; leave unset (defaults `false`) anywhere else |

   Leave `DATABASE_URL`/`STORAGE_DIR`/`CHROMA_DIR` **unset**: Spaces has
   no mounted volume, so there is no `/data`-style absolute path to point
   them at. `Settings`' existing defaults (`sqlite:///./data/...`,
   `./data`, `./data/chroma`) resolve relative to the container's
   `WORKDIR` (`/app/backend`) instead, and the `Dockerfile`'s non-root
   `appuser` already owns that directory tree (`chown -R appuser:appuser
   /app ...`), so it can create `./data` on demand — the same mechanism
   local dev already relies on, just running inside the container. This
   is intentional, not an oversight: pointing these at a real path would
   imply persistence that the free tier can't actually provide.

   `CORS_ORIGINS` is unneeded here for the same same-origin reason as
   Railway (see below) — leave it unset.

4. **Port**: `entrypoint.sh` already runs `uvicorn ... --port
   "${PORT:-8000}"`. Spaces' Docker SDK doesn't inject a `$PORT` env var
   the way Railway does — it routes to whatever port the Space's
   `app_port` front-matter field declares. `README_SPACE.md` sets
   `app_port: 8000`, which matches our `${PORT:-8000}` default exactly,
   so no entrypoint change was needed here — verified, not assumed.

5. **Build and watch the Space's build logs.** Same expectations as
   local: `alembic upgrade head` runs before `uvicorn` starts (SDD 3.7's
   "DB migrations run as a release step"), then — because
   `SEED_DEMO_DOCUMENT=true` — the demo PDF ingests on that same cold
   start before the app reports ready. A Space rebuild/restart repeats
   this from scratch every time (ephemeral storage), which is expected,
   not a failure.

### Local verification (Spaces-style defaults)

From the repo root, deliberately **omitting** `DATABASE_URL`/
`STORAGE_DIR`/`CHROMA_DIR` to prove the bare defaults work the way
Spaces will actually run them:

```bash
docker build -t hr-assistant .

docker run --rm -p 8000:8000 \
  -e SEED_DEMO_DOCUMENT=true \
  -e APP_ENV=production \
  -e GEMINI_API_KEY=<real key> \
  -e GEMINI_MODEL_NAME=gemini-3.5-flash \
  -e GROUNDEDNESS_REJECT_THRESHOLD=0.10 \
  -e GROUNDEDNESS_COMFORTABLE_THRESHOLD=0.13 \
  hr-assistant
```

Then confirm:

1. `curl localhost:8000/api/v1/health` → 200.
2. `curl localhost:8000/api/v1/documents` → `total: 1`, `status: READY` —
   the demo PDF seeded itself without ever hitting `/upload`.
3. `http://localhost:8000/` loads the SPA; ask the demo question from
   `README_SPACE.md` in chat and confirm a grounded, cited answer.
4. `docker stop` + `docker run` the same command again (no volume this
   time — that's the point) → still exactly one document, same content
   (proves the seed's SHA-256 dedup check, not a fresh duplicate every
   restart).

## Railway (documented alternative, ADR-011)

Kept as a documented, working alternative — not the active deployment.
Deploys the same root `Dockerfile` as **one** Railway service, backed by
a real mounted volume (unlike Spaces, Railway gives true persistence).

### Prerequisites

- The image builds and runs cleanly locally first.
- A Gemini API key (`docs/threshold-calibration.md` if you're swapping
  models).

### Steps

1. **New Railway project → "Deploy from GitHub repo"**, pointing at this
   repository. Railway auto-detects the root `Dockerfile` — no
   `railway.json`/Nixpacks config needed.
2. **Attach a volume**, mount path `/data`. This is the *only* persistent
   state: SQLite DB, uploaded PDFs, and the Chroma vector index all live
   under it. Without this volume, a redeploy wipes every document and
   conversation.
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

   `SEED_DEMO_DOCUMENT` is a Spaces-specific concern - leave it unset
   (defaults `false`) here, since Railway's real volume means the demo
   document persists on its own once uploaded once.

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

### Rollback

Redeploy the previous image tag from Railway's deploy history (SDD
3.7's stated rollback strategy - no separate runbook needed, it's a
built-in platform feature).

### Local verification (run this before every Railway deploy)

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
