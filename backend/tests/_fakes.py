"""Shared test doubles (leading underscore so pytest never collects this
as a test module itself).

FakeLLMService implements the full LLMService Protocol (app.services.
llm_service) so /chat and the golden evaluation set can exercise real
retrieval/ranking/prompt/citation logic without ever calling Gemini.
"""

from collections.abc import Callable

from app.services.llm_service import LLMResult


class FakeLLMService:
    def __init__(self, respond: Callable[[str], str] | None = None) -> None:
        """respond(prompt) -> text; defaults to echoing every [S#] tag
        found in the prompt back in the answer, which is enough to give
        any answerable case a valid, deterministic citation to assert on
        without needing per-question canned answers."""
        self._respond = respond or _default_response
        self.calls: list[str] = []
        self.raise_error: Exception | None = None

    def generate(self, prompt: str) -> LLMResult:
        self.calls.append(prompt)
        if self.raise_error is not None:
            raise self.raise_error

        text = self._respond(prompt)
        return LLMResult(
            text=text,
            prompt_tokens=len(prompt.split()),
            completion_tokens=len(text.split()),
            latency_ms=1,
            finish_reason="STOP",
        )


def _default_response(prompt: str) -> str:
    """Echoes each <source> tag's own text back, immediately followed by
    its citation tag - not just a canned citation, since Module 7 wires
    the real Response Validation Agent into /chat: a generic filler
    answer has near-zero lexical overlap with the source text and gets
    rejected by the real groundedness gate. Echoing the source verbatim
    guarantees full overlap, so any answerable case still produces a
    valid, deterministic, *groundedness-passing* citation to assert on."""
    import re

    sources = re.findall(r'<source id="(S\d+)"[^>]*>\n(.*?)\n</source>', prompt, re.DOTALL)
    if not sources:
        return "NOT_FOUND"
    return " ".join(f"{text.strip()} [{tag}]" for tag, text in sources)
