"""LLM service (SDD Section 6.3.6, Section 7.2 Stage 10, ADR-009).

Sole owner of the Gemini generation call. Interface first
(`LLMService` Protocol) so the concrete provider is swappable without
touching callers; `GeminiLLMService` is the adapter, using the official
`google-genai` SDK.

The circuit breaker's state is process-wide (module-level singleton,
`_circuit_state`) even though `GeminiLLMService` itself is constructed
fresh per call site, like `StorageService`/`ChromaVectorStore` - the
breaker needs to persist across requests to mean anything, but there's
no other per-instance state worth keeping alive, so a full registry
(like the embedder's) would be overkill here.
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from typing import Protocol

from google import genai
from google.genai import errors, types

from app.core.config import Settings
from app.core.exceptions import GenerationTimeoutError, LlmQuotaExceededError, LlmUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LLMResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    finish_reason: str | None


class LLMService(Protocol):
    def generate(self, prompt: str) -> LLMResult: ...


class _CircuitBreakerState:
    """Not literally in the SDD text: after `failure_threshold` consecutive
    failures the breaker opens and fast-fails every call; after
    `cooldown_seconds` it allows exactly one trial call through
    (half-open). A renewed failure during that trial re-arms the full
    cooldown from that failure, not the original one. Without this, an
    open breaker would stay open until process restart, which reads more
    like an oversight than the intent behind "fast-fail" resilience."""

    def __init__(self) -> None:
        self.consecutive_failures = 0
        self.opened_at: float | None = None

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self, *, failure_threshold: int) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= failure_threshold:
            self.opened_at = time.monotonic()

    def is_open(self, *, cooldown_seconds: int) -> bool:
        if self.opened_at is None:
            return False
        return time.monotonic() - self.opened_at < cooldown_seconds


_circuit_state = _CircuitBreakerState()


class GeminiLLMService:
    """Constructing this never touches the network or validates the API
    key - the genai.Client is built lazily on first actual use. FastAPI
    resolves LLMServiceDep on every /chat request regardless of whether
    the route ends up calling generate() (e.g. the pre-LLM NOT_FOUND
    short-circuit never does), so eager client construction here would
    mean every request pays that cost - and fails outright without a
    configured API key even when the LLM is never actually needed."""

    def __init__(self, settings: Settings, *, client: genai.Client | None = None) -> None:
        self._settings = settings
        self._client = client

    def _get_client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                api_key=self._settings.gemini_api_key.get_secret_value()
            )
        return self._client

    def generate(self, prompt: str) -> LLMResult:
        settings = self._settings
        if _circuit_state.is_open(
            cooldown_seconds=settings.gemini_circuit_breaker_cooldown_seconds
        ):
            raise LlmUnavailableError()

        started_at = time.perf_counter()

        for attempt in range(settings.gemini_max_retries + 1):
            try:
                response = self._call_with_timeout(prompt, settings.gemini_timeout_seconds)
            except FutureTimeoutError as exc:
                _circuit_state.record_failure(
                    failure_threshold=settings.gemini_circuit_breaker_failure_threshold
                )
                raise GenerationTimeoutError() from exc
            except errors.ClientError as exc:
                if exc.code == 429 and attempt < settings.gemini_max_retries:
                    self._sleep_backoff(attempt)
                    continue
                _circuit_state.record_failure(
                    failure_threshold=settings.gemini_circuit_breaker_failure_threshold
                )
                if exc.code == 429:
                    raise LlmQuotaExceededError() from exc
                raise LlmUnavailableError() from exc
            except errors.ServerError as exc:
                if attempt < settings.gemini_max_retries:
                    self._sleep_backoff(attempt)
                    continue
                _circuit_state.record_failure(
                    failure_threshold=settings.gemini_circuit_breaker_failure_threshold
                )
                raise LlmUnavailableError() from exc
            else:
                _circuit_state.record_success()
                return _to_llm_result(response, latency_ms=self._elapsed_ms(started_at))

        raise AssertionError("unreachable: loop always returns or raises")

    def _call_with_timeout(
        self, prompt: str, timeout_seconds: float
    ) -> types.GenerateContentResponse:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self._call_gemini, prompt)
            return future.result(timeout=timeout_seconds)

    def _call_gemini(self, prompt: str) -> types.GenerateContentResponse:
        settings = self._settings
        return self._get_client().models.generate_content(
            model=settings.gemini_model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=settings.gemini_temperature,
                max_output_tokens=settings.gemini_max_output_tokens,
            ),
        )

    def _sleep_backoff(self, attempt: int) -> None:
        base = self._settings.gemini_retry_base_delay_seconds
        delay = base * (2**attempt) + random.uniform(0, base / 2)
        time.sleep(delay)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return round((time.perf_counter() - started_at) * 1000)


def _to_llm_result(response: types.GenerateContentResponse, *, latency_ms: int) -> LLMResult:
    usage = response.usage_metadata
    finish_reason = None
    if response.candidates:
        finish_reason = response.candidates[0].finish_reason
    return LLMResult(
        text=response.text or "",
        prompt_tokens=usage.prompt_token_count if usage and usage.prompt_token_count else 0,
        completion_tokens=(
            usage.candidates_token_count if usage and usage.candidates_token_count else 0
        ),
        latency_ms=latency_ms,
        finish_reason=str(finish_reason) if finish_reason is not None else None,
    )
