"""Typed application settings loaded from environment variables / .env.

Single source of truth for all configuration (SDD Section 3.5): no other
module should read os.environ directly or embed a default value that
belongs here.
"""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    app_name: str = "Enterprise HR Policy AI Assistant"
    app_version: str = "0.1.0"
    app_env: Literal["local", "staging", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # --- Database (Section 8.1: SQLite v1 -> Postgres later, connection-string swap only) ---
    database_url: str = "sqlite:///./data/hr_assistant.db"

    # --- CORS (raw comma-separated string; pydantic-settings would try to
    # JSON-decode a list[str] env var, which breaks on plain "a, b" values) ---
    cors_origins: str = "http://localhost:5173"

    # --- File storage (SDD Section 9: storage_service.py; local -> S3 later) ---
    storage_dir: str = "./data"

    # --- Upload limits (FR-D01, FR-D02, FR-D03) ---
    upload_max_file_mb: int = 25
    upload_max_files: int = 10

    # --- Ingestion / PDF processing (SDD Section 7 Stage 2, Section 11.4) ---
    ingestion_pdf_timeout_seconds: int = 30
    ingestion_max_pages: int = 500
    min_extractable_chars_per_page: int = 20

    # --- Chunking (SDD Section 7.2 Stage 3, docs/chunking-decision.md) ---
    chunk_target_tokens: int = 600
    chunk_overlap_tokens: int = 100

    # --- Embeddings (SDD Section 7.2 Stage 5, Appendix A, ADR-002) ---
    embedding_model_hf_id: str = "BAAI/bge-small-en-v1.5"
    embedding_batch_size: int = 32

    # --- Vector store (SDD Section 7.2 Stage 6, ADR-009) ---
    chroma_dir: str = "./data/chroma"

    # --- Retrieval & ranking (SDD Section 6.3.3/6.3.4, 7.2 Stage 7-8) ---
    retrieval_top_k: int = 8
    # The SDD's illustrative "~0.35" is superseded by measurement
    # (docs/threshold-calibration.md, scripts/calibrate_threshold.py):
    # BAAI/bge-small-en-v1.5's raw cosine similarity for short text pairs
    # sits in a ~0.3-0.5 band regardless of topical relevance (a known
    # anisotropy property of sentence embedding models), so 0.35 barely
    # rejects anything. 0.50 was picked from a real calibration run
    # against the golden-set fixture: off-topic questions topped out at
    # 0.44, on-topic questions started at 0.60.
    retrieval_similarity_threshold: float = 0.50
    # Recalibrated alongside the threshold above, from the same run: the
    # answerable-question score spread was 0.60-0.85, so 0.65 gives a
    # meaningful high/low split instead of being a no-op right at (or
    # below) the gate.
    retrieval_high_confidence_threshold: float = 0.65
    context_token_budget: int = 2000
    context_max_blocks: int = 4
    mmr_lambda: float = 0.5

    # --- Response validation groundedness (SDD Section 6.3.7) ---
    # Measured, not guessed (docs/threshold-calibration.md, "Response
    # validation groundedness" and "Model swap re-run" sections;
    # scripts/calibrate_threshold.py). Re-calibrated after the
    # gemini-2.5-flash -> gemini-3.5-flash swap using --live (real
    # answers from the real model, not hand-written examples): weakest
    # per-answer Jaccard score across 10 real answerable-question answers
    # was 0.13-0.38 (min 0.1333). The fixture was also fixed in this
    # pass (it was truncated mid-sentence, silently starving several
    # golden questions of their own answer) - full-paragraph sources have
    # much larger vocabularies than the old truncated ~130-char chunks,
    # which naturally pulls every Jaccard score down and narrows the
    # grounded/fabricated gap versus the original calibration. 0.10 sits
    # with margin below the real measured floor, biased toward not
    # rejecting genuine (if terse) live answers - this heuristic is a
    # secondary, lexical-only gate; the pre-LLM retrieval threshold and
    # Citation Agent's tag-validity check are independent gates on the
    # same answer. 0.13 sits just under the measured floor, so claims
    # between the two are downgraded to LOW confidence rather than
    # rejected outright.
    groundedness_reject_threshold: float = 0.10
    groundedness_comfortable_threshold: float = 0.13

    # --- Prompt building (SDD Section 6.3.5, 7.2 Stage 9) ---
    # Deliberately a bit above context_token_budget: ranking's budget
    # covers chunk text only, while this covers the fully-assembled
    # prompt (system rules + <source>/<question> tag overhead too) - an
    # independent second check, not a duplicate of the same number.
    prompt_token_budget: int = 2400

    # --- LLM / Gemini (SDD Section 6.3.6, 7.2 Stage 10, ADR-009) ---
    # SecretStr so the key is never accidentally logged (e.g. via structlog's
    # automatic repr of a Settings/exception object) - only unwrapped with
    # get_secret_value() at the point the genai client is constructed.
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model_name: str = "gemini-3.5-flash"
    gemini_temperature: float = 0.1
    gemini_max_output_tokens: int = 1024
    # Re-measured after the gemini-2.5-flash -> gemini-3.5-flash swap
    # (docs/threshold-calibration.md "Model swap re-run"): real calls to
    # gemini-3.5-flash were observed taking up to ~19-30s, leaving too
    # little margin under the old 20s default.
    gemini_timeout_seconds: float = 45.0
    gemini_max_retries: int = 3
    gemini_retry_base_delay_seconds: float = 1.0
    gemini_circuit_breaker_failure_threshold: int = 5
    gemini_circuit_breaker_cooldown_seconds: int = 30

    # --- Rate limiting - edge tier (Section 11.6) ---
    rate_limit_per_minute: int = 10
    rate_limit_window_seconds: int = 60

    # --- Sessions (FR-S06) ---
    session_ttl_hours: int = 24
    # SDD Section 8.3: "title: auto-titled from first question".
    session_title_max_chars: int = 60

    # --- Conversation memory (SDD Section 6.3.9, FR-S05) ---
    memory_window_turns: int = 6
    memory_summary_refresh_interval_turns: int = 6

    # --- Middleware seams (Section 5.3, 6.3.1) ---
    request_id_header: str = "X-Request-ID"
    auth_header_name: str = "X-User-Id"

    # --- Default tenant/user seed (single-tenant v1, ADR-007) ---
    default_tenant_id: str = "00000000-0000-0000-0000-000000000001"
    default_tenant_name: str = "Default Tenant"
    default_user_id: str = "00000000-0000-0000-0000-000000000002"
    default_user_email: str = "admin@example.com"
    default_user_display_name: str = "Default Admin"

    # --- Static frontend serving (single-service container deployment,
    # ADR-011/ADR-012) --- Empty in local dev/tests, where the frontend
    # runs on its own Vite dev server via the proxy in vite.config.ts. The
    # Dockerfile's runtime image sets this so app/api/spa.py mounts the
    # built SPA and FastAPI serves it same-origin.
    frontend_dist_dir: str = ""

    # --- Demo document seeding (Hugging Face Spaces, ADR-012) --- Spaces'
    # free tier has ephemeral storage (the filesystem resets on every
    # restart/rebuild), so the deployed demo re-seeds a bundled sample PDF
    # on every cold start if the tenant has no documents yet. False by
    # default so local dev/tests are unaffected; the Space sets this true.
    seed_demo_document: bool = False

    @property
    def cors_origins_list(self) -> list[str]:
        """Parsed CORS_ORIGINS: comma-separated string -> list of origins."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached Settings instance; use via FastAPI Depends(get_settings)."""
    return Settings()
