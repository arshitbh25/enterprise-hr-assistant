"""Unit tests for app/services/llm_service.py (SDD Section 6.3.6).

A fake low-level genai client (just implements .models.generate_content)
is injected via GeminiLLMService's constructor seam, so these tests
drive real retry/backoff/circuit-breaker/timeout logic deterministically
without any real network call. The one exception is
test_live_smoke_call, marked `live_llm` and skipped unless a real
GEMINI_API_KEY is present in the environment.

To run the live test for real:
    set GEMINI_API_KEY=<a real key>
    pytest tests/unit/test_services_llm_service.py -m live_llm
"""

import os
import time
from types import SimpleNamespace

import pytest
from google.genai import errors

from app.core.config import Settings
from app.core.exceptions import (
    GenerationTimeoutError,
    LlmQuotaExceededError,
    LlmUnavailableError,
)
from app.services import llm_service as llm_service_module
from app.services.llm_service import GeminiLLMService


@pytest.fixture(autouse=True)
def _reset_circuit_breaker():
    state = llm_service_module._circuit_state
    state.consecutive_failures = 0
    state.opened_at = None
    yield
    state.consecutive_failures = 0
    state.opened_at = None


def _settings(**overrides) -> Settings:
    defaults = dict(
        gemini_api_key="fake-key",
        gemini_max_retries=3,
        gemini_retry_base_delay_seconds=0.01,
        gemini_timeout_seconds=5,
        gemini_circuit_breaker_failure_threshold=5,
        gemini_circuit_breaker_cooldown_seconds=30,
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def _success_response(
    text: str = "Answer text. [S1]",
    prompt_tokens: int = 10,
    completion_tokens: int = 5,
    finish_reason: str = "STOP",
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens, candidates_token_count=completion_tokens
        ),
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )


class _FakeModels:
    def __init__(self, outcomes: list, *, sleep_seconds: float = 0.0) -> None:
        self._outcomes = list(outcomes)
        self._sleep_seconds = sleep_seconds
        self.call_count = 0

    def generate_content(self, *, model, contents, config):
        self.call_count += 1
        if self._sleep_seconds:
            time.sleep(self._sleep_seconds)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes: list, *, sleep_seconds: float = 0.0) -> None:
        self.models = _FakeModels(outcomes, sleep_seconds=sleep_seconds)


def _client_error(code: int) -> errors.ClientError:
    return errors.ClientError(code, {"message": "error", "status": "ERROR"})


def _server_error(code: int) -> errors.ServerError:
    return errors.ServerError(code, {"message": "error", "status": "ERROR"})


def test_successful_call_returns_llm_result():
    client = _FakeClient([_success_response()])
    service = GeminiLLMService(_settings(), client=client)

    result = service.generate("prompt")

    assert result.text == "Answer text. [S1]"
    assert result.prompt_tokens == 10
    assert result.completion_tokens == 5
    assert result.finish_reason == "STOP"
    assert result.latency_ms >= 0
    assert client.models.call_count == 1


def test_retries_on_429_then_succeeds():
    client = _FakeClient([_client_error(429), _success_response()])
    service = GeminiLLMService(_settings(), client=client)

    result = service.generate("prompt")

    assert result.text == "Answer text. [S1]"
    assert client.models.call_count == 2


def test_429_exhausts_retries_raises_quota_exceeded():
    client = _FakeClient([_client_error(429)] * 4)  # 1 initial + 3 retries
    service = GeminiLLMService(_settings(gemini_max_retries=3), client=client)

    with pytest.raises(LlmQuotaExceededError):
        service.generate("prompt")

    assert client.models.call_count == 4


def test_5xx_exhausts_retries_raises_unavailable():
    client = _FakeClient([_server_error(503)] * 4)
    service = GeminiLLMService(_settings(gemini_max_retries=3), client=client)

    with pytest.raises(LlmUnavailableError):
        service.generate("prompt")

    assert client.models.call_count == 4


def test_timeout_raises_generation_timeout():
    client = _FakeClient([_success_response()], sleep_seconds=0.5)
    service = GeminiLLMService(_settings(gemini_timeout_seconds=0.05), client=client)

    with pytest.raises(GenerationTimeoutError):
        service.generate("prompt")


def test_circuit_breaker_opens_after_consecutive_failures_and_fast_fails():
    settings = _settings(
        gemini_max_retries=0,
        gemini_circuit_breaker_failure_threshold=2,
        gemini_circuit_breaker_cooldown_seconds=999,
    )

    failing_client_1 = _FakeClient([_server_error(500)])
    with pytest.raises(LlmUnavailableError):
        GeminiLLMService(settings, client=failing_client_1).generate("prompt")

    failing_client_2 = _FakeClient([_server_error(500)])
    with pytest.raises(LlmUnavailableError):
        GeminiLLMService(settings, client=failing_client_2).generate("prompt")

    # Breaker is now open (2 consecutive failures >= threshold of 2) -
    # a third call must fast-fail without ever reaching the client.
    never_called_client = _FakeClient([_success_response()])
    with pytest.raises(LlmUnavailableError):
        GeminiLLMService(settings, client=never_called_client).generate("prompt")

    assert never_called_client.models.call_count == 0


def test_circuit_breaker_cooldown_allows_half_open_retry():
    settings = _settings(
        gemini_max_retries=0,
        gemini_circuit_breaker_failure_threshold=1,
        gemini_circuit_breaker_cooldown_seconds=0,
    )

    failing_client = _FakeClient([_server_error(500)])
    with pytest.raises(LlmUnavailableError):
        GeminiLLMService(settings, client=failing_client).generate("prompt")

    # Cooldown is 0s, so the breaker is immediately half-open: the next
    # call must reach the client again rather than fast-failing.
    recovering_client = _FakeClient([_success_response()])
    result = GeminiLLMService(settings, client=recovering_client).generate("prompt")

    assert result.text == "Answer text. [S1]"
    assert recovering_client.models.call_count == 1


@pytest.mark.live_llm
def test_live_smoke_call():
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set; skipping live Gemini call")

    service = GeminiLLMService(Settings())
    result = service.generate("Reply with exactly one word: hello")

    assert result.text.strip()
