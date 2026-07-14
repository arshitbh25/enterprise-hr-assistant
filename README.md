# Enterprise HR Policy AI Assistant

An **Agentic RAG** chatbot that answers employee HR-policy questions strictly from a company's own uploaded policy PDFs — every answer is grounded, cited (document + page), and the system refuses rather than guesses when it isn't confident. Employees get instant, consistent answers instead of a support-ticket queue; HR gets an audit trail of every question the bot did and didn't answer.

Full design rationale, trade-off analysis, and API/DB specs live in [`docs/sdd.md`](docs/sdd.md) — that document is the source of truth this codebase was built against. This README is the "how do I run it" companion.

## Why Agentic RAG

A raw or fine-tuned LLM can't guarantee it won't fabricate a policy answer, and fine-tuned weights can't "unlearn" a deleted or superseded document. This project instead decomposes the pipeline into small, testable agents (query understanding → retrieval → ranking → prompt construction → generation → **response validation** → citation), with a deliberate double groundedness gate: weak retrieval never reaches the LLM, and a post-generation validator fails closed to a standard "not found in the uploaded documents" message rather than ever letting an ungrounded claim through. See [`docs/sdd.md`](docs/sdd.md) Section 4 for the full comparison against keyword search, vanilla RAG, and fine-tuning, and [`docs/agent-architecture.md`](docs/agent-architecture.md) for the as-built agent contracts.

## Tech stack

| Layer | Choice |
|---|---|
| Backend | FastAPI, SQLAlchemy + Alembic, Pydantic / pydantic-settings |
| Retrieval | ChromaDB (persistent, embedded) + `BAAI/bge-small-en-v1.5` local embeddings ([why](docs/sdd.md#14-appendix-a--embedding-model-selection)) |
| Generation | Google Gemini, isolated behind an `LLMService` port (provider swap = one module) |
| Frontend | React + TypeScript + Vite + Tailwind CSS |
| Storage | SQLite (dev; Postgres is a connection-string swap) + local file storage for original PDFs |

## Project status

Built module-by-module against an approved plan, each reviewed before the next started.

**Phase P6 — Agent Workflow (backend):** complete. The full 9-agent pipeline (`app/agents/`) is wired through `POST /chat`, with fail-closed/fail-soft behavior proven via fault-injection tests, not just happy-path tests.

**Phase P7 — Frontend:** complete.
- Chat page — message bubbles, expandable citation cards, confidence badges, starter-question chips
- Documents page — drag-and-drop upload with client-side pre-checks, live ingestion-status polling, delete with confirmation
- Sessions & history sidebar — switch between past conversations, auto-titled from the first question, delete with confirmation
- Polish — a toast system covering every documented error code (with a live Retry-After countdown on rate limits), a top-level error boundary, loading skeletons, and a responsive off-canvas sidebar on mobile

271 backend tests passing (`pytest -q`, 1 skipped without a live Gemini key), `ruff` clean. Frontend `tsc -b`, `oxlint`, a light `vitest` suite (`npm test` — `apiClient` error-mapping and a `CitationCard` render test), and a real production build (`npm run build`) all pass clean.

**Deliberately deferred** (portfolio scope — see [Known limitations](#known-limitations--future-work)): a full accessibility/keyboard-navigation pass, offline detection, and everything in [`docs/sdd.md`](docs/sdd.md) Section 12 (hybrid search, reranking, RBAC, streaming responses, OCR, deployment/CI).

## Getting started

### Prerequisites

- Python 3.11+
- Node.js + npm
- A [Gemini API key](https://ai.google.dev/) (free tier is enough) — only required for live chat *generation*; everything else, including the full test suite, works without one

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -e ".[dev]"

copy .env.example .env          # Windows; `cp` on macOS/Linux
# then set GEMINI_API_KEY in .env for real chat generation

alembic upgrade head            # creates the schema; the app fails fast at boot if this is skipped
uvicorn app.main:create_app --factory --reload
```

The API is now at `http://localhost:8000`; `GET /api/v1/health` reports readiness. First boot downloads and caches the ~130 MB embedding model from Hugging Face — expect a slower cold start once.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The app is now at `http://localhost:5173`, proxying `/api` to the backend dev server (see `vite.config.ts`). `frontend/.env.example` documents the (optional) client-side env vars — see [Environment variables](#environment-variables).

### Running tests

```bash
# Backend
cd backend
pytest -q
ruff check .

# Frontend
cd frontend
npx tsc -b
npm run lint
npm test        # vitest: apiClient error-mapping + a CitationCard render test
npm run build   # real production build, not just the dev-server transform
```

## Environment variables

Backend config is entirely `pydantic-settings`-driven — see [`backend/.env.example`](backend/.env.example) for the full list with inline rationale (chunking sizes, retrieval/groundedness thresholds calibrated against a real fixture — see [`docs/threshold-calibration.md`](docs/threshold-calibration.md) — rate limits, session TTL, etc.). Nothing is hardcoded; nothing sensitive is checked in.

Frontend env vars are optional (see [`frontend/.env.example`](frontend/.env.example)): `VITE_API_BASE_URL` for a non-proxied deployment, and `VITE_MAX_FILE_MB`/`VITE_MAX_FILES` for client-side upload pre-checks, which should match the backend's own limits.

## Troubleshooting

**Chat generation fails with a 404 from Gemini.** The model in `GEMINI_MODEL_NAME` has most likely been retired — Google periodically deprecates older Gemini model names. List the models your API key currently has access to and update `GEMINI_MODEL_NAME` in `.env` accordingly:

```bash
python -c "from google import genai; c = genai.Client(); [print(m.name) for m in c.models.list()]"
```

After swapping models, re-run the groundedness calibration (`python scripts/calibrate_threshold.py --live`, requires `GEMINI_API_KEY`) — a different model's phrasing style can shift how it scores against `GROUNDEDNESS_REJECT_THRESHOLD`/`GROUNDEDNESS_COMFORTABLE_THRESHOLD`, and blindly swapping the model name without recalibrating risks either false refusals or under-validated answers. See [`docs/threshold-calibration.md`](docs/threshold-calibration.md)'s "Model swap re-run" section for a worked example of this happening on the `gemini-2.5-flash` → `gemini-3.5-flash` swap.

## Project structure

Dependency direction is strictly inward: `api → agents → services → infrastructure`. Agents never touch an external system directly — only through `services/`. Prompts are versioned files under `backend/app/prompts/`, never inline strings, so prompt changes are reviewable diffs. Full rationale in [`docs/sdd.md`](docs/sdd.md) Section 9.

```
backend/app/
  api/          REST routers + Pydantic request/response schemas
  agents/       the 9-agent pipeline + orchestrator (SDD Section 6)
  services/     ports to external systems (Gemini, ChromaDB, file storage)
  rag/          ingestion-plane logic (PDF parsing, chunking, ranking, citations)
  embeddings/   local embedding model lifecycle
  database/     SQLAlchemy models + per-aggregate repositories
  core/         typed Settings, structured logging, domain exceptions
  prompts/      versioned prompt templates

frontend/src/
  pages/        ChatPage, DocumentsPage
  components/   presentational components (render only)
  hooks/        useChat, useDocuments, useSessions (own all state)
  context/      ToastContext (the app's single error/notice surface)
  services/     apiClient.ts (the only module that touches fetch/URLs)
  types/        TS interfaces mirroring the backend's Pydantic schemas
```

## Known limitations & future work

Honestly scoped, not accidental gaps:

- **No OCR** — scanned/image PDFs aren't extracted (flagged at ingestion via a low-text-ratio heuristic, not silently mis-processed).
- **No hybrid search or reranking yet** — retrieval is dense-embedding-only; `docs/sdd.md` Section 12.1/12.2 designs the drop-in upgrade path.
- **No accessibility/keyboard-navigation pass** — deferred as portfolio scope; a real production rollout would need one before shipping.
- **Light frontend test coverage** — `vitest` covers `apiClient`'s error-mapping (the highest-risk piece of untested logic) and one component render test, not full component/hook coverage; the backend's 271-test suite is the primary correctness net.
- **No offline detection** — a dropped connection surfaces as a generic network-error toast rather than a dedicated offline state.
- **No RBAC** — single-tenant, single-role v1; the `tenant_id`/`role` columns exist from day one specifically so this is additive, not a retrofit (Section 12.5).
- **No deployment/CI yet** — no Dockerfile, docker-compose, or GitHub Actions workflow; Phase P9 in the SDD roadmap.
- **English-only**, informational-not-authoritative by design (every answer includes an "HR remains the final authority" disclaimer).

See [`docs/sdd.md`](docs/sdd.md) Section 12 for the full future-enhancements list with where each one plugs into the existing architecture.
