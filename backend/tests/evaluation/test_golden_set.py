"""Golden evaluation set (SDD Section 13 P5 exit criteria: "Golden set v0
(20 Q&A): 100% citation presence, 0 fabricated answers on adversarial
'not in doc' questions").

Runs entirely offline by default via FakeLLMService (tests/_fakes.py) -
no real Gemini calls, no network dependency, deterministic. Retrieval,
ranking, and the real similarity threshold gate all run for real
against tests/evaluation/fixtures/sample_hr_policy.pdf.

Per docs/threshold-calibration.md, adversarial cases split into two
tiers with different guarantees:
- OFF_TOPIC: rejected by the real retrieval_similarity_threshold gate
  on real scores (measured 0.30-0.44, well below the 0.50 threshold) -
  the LLM is never called. This IS a real, offline-provable guarantee.
- TOPICALLY_ADJACENT: scores above the threshold (measured 0.61-0.72)
  and genuinely reaches the LLM. The fake LLM here is configured to
  emit the exact NOT_FOUND token, which only proves the citation/
  refusal-normalization plumbing correctly converts that into a
  NOT_FOUND response - it does NOT prove a real Gemini call would
  comply. That can only be verified live.

To run the topically-adjacent tier against the real Gemini API:
    1. Set a real GEMINI_API_KEY in the environment.
    2. In test_topically_adjacent_cases_rely_on_llm_refusal_normalization,
       remove the dependency_overrides line (or delete it after the
       fixture yields) so /chat falls through to the real
       GeminiLLMService instead of the fake.
    3. Run: pytest tests/evaluation/test_golden_set.py -k
       test_topically_adjacent_cases_rely_on_llm_refusal_normalization
This is the priority case for a live run - it's the one guarantee this
offline suite cannot make on its own.
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from alembic import command
from alembic.config import Config
from app.api.deps import get_llm_service
from app.core.config import Settings, get_settings
from app.core.constants import NOT_FOUND_TOKEN
from app.main import create_app
from tests._fakes import FakeLLMService, _default_response
from tests.evaluation.golden_qa import (
    ADVERSARIAL_CASES,
    ANSWERABLE_CASES,
    MULTI_TURN_CASES,
    AdversarialTier,
)

pytestmark = pytest.mark.model

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "sample_hr_policy.pdf"


@pytest.fixture(scope="module")
def golden_client(tmp_path_factory: pytest.TempPathFactory):
    tmp_path = tmp_path_factory.mktemp("golden")
    database_url = f"sqlite:///{(tmp_path / 'golden.db').as_posix()}"

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()

    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")

    settings = Settings(
        _env_file=None,
        database_url=database_url,
        storage_dir=str(tmp_path / "storage"),
        chroma_dir=str(tmp_path / "chroma"),
        # This harness deliberately fires 20 rapid /chat requests from one
        # client to evaluate every golden case - the per-IP edge rate
        # limit (Section 11.6) is a real-user protection, not something
        # this evaluation run should trip over.
        rate_limit_per_minute=1000,
    )

    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/v1/upload",
            files=[
                (
                    "files",
                    ("sample_hr_policy.pdf", FIXTURE_PATH.read_bytes(), "application/pdf"),
                )
            ],
        )
        assert response.status_code == 202
        yield client

    if previous_database_url is None:
        os.environ.pop("DATABASE_URL", None)
    else:
        os.environ["DATABASE_URL"] = previous_database_url
    get_settings.cache_clear()


def test_answerable_cases_have_100_percent_citation_presence(golden_client: TestClient):
    fake = FakeLLMService()
    golden_client.app.dependency_overrides[get_llm_service] = lambda: fake

    failures = []
    for case in ANSWERABLE_CASES:
        response = golden_client.post(
            "/api/v1/chat", json={"session_id": None, "question": case.question}
        )
        body = response.json()
        if response.status_code != 200 or body["not_found"] or not body["citations"]:
            failures.append((case.question, response.status_code, body))

    assert not failures, (
        f"{len(failures)}/{len(ANSWERABLE_CASES)} answerable cases failed: {failures}"
    )


def test_off_topic_adversarial_cases_rejected_by_real_threshold_gate(golden_client: TestClient):
    """No monkeypatching: these must be rejected by real retrieval scores
    against the real fixture, and must never reach the LLM at all."""
    fake = FakeLLMService()
    golden_client.app.dependency_overrides[get_llm_service] = lambda: fake

    off_topic_cases = [c for c in ADVERSARIAL_CASES if c.tier is AdversarialTier.OFF_TOPIC]
    failures = []
    for case in off_topic_cases:
        response = golden_client.post(
            "/api/v1/chat", json={"session_id": None, "question": case.question}
        )
        body = response.json()
        if not body.get("not_found"):
            failures.append((case.question, body))

    assert not failures, f"off-topic cases incorrectly answered: {failures}"
    assert fake.calls == [], "off-topic cases must be rejected before ever calling the LLM"


def test_topically_adjacent_cases_rely_on_llm_refusal_normalization(golden_client: TestClient):
    """These reach the LLM for real (real scores 0.61-0.72, above
    threshold). Configuring the fake to emit NOT_FOUND verifies the
    citation/refusal-normalization plumbing only - see the module
    docstring for why this cannot prove real model compliance, and how
    to run this specific test against the real Gemini API instead."""
    fake = FakeLLMService(respond=lambda prompt: NOT_FOUND_TOKEN)
    golden_client.app.dependency_overrides[get_llm_service] = lambda: fake

    adjacent_cases = [
        c for c in ADVERSARIAL_CASES if c.tier is AdversarialTier.TOPICALLY_ADJACENT
    ]
    failures = []
    for case in adjacent_cases:
        response = golden_client.post(
            "/api/v1/chat", json={"session_id": None, "question": case.question}
        )
        body = response.json()
        if not body.get("not_found"):
            failures.append((case.question, body))

    assert not failures, f"topically-adjacent cases incorrectly answered: {failures}"
    assert len(fake.calls) == len(adjacent_cases), (
        "topically-adjacent cases are expected to clear the retrieval gate "
        "and reach the LLM, unlike the off-topic tier"
    )


def test_multi_turn_follow_ups_resolve_through_real_retrieval(golden_client: TestClient):
    """SDD §13 P6 exit criterion: 'multi-turn eval passes ("and for
    interns?" resolves correctly)'. Only the rewrite call's own output
    text is faked (per-case, keyed off the exact follow-up question);
    everything downstream - real BGE embedding, real ChromaDB retrieval
    against the real fixture, real ranking, real prompt construction,
    real citation resolution - runs unmodified. A case only passes if the
    real retrieval path genuinely finds and cites the right section for
    the *rewritten* query, proving Memory -> Query Understanding ->
    Retriever are actually wired together, not just individually correct."""
    failures = []
    for case in MULTI_TURN_CASES:

        def _respond(prompt: str, _case=case) -> str:
            if "Follow-up question:" in prompt:
                return _case.rewritten_follow_up
            return _default_response(prompt)

        fake = FakeLLMService(respond=_respond)
        golden_client.app.dependency_overrides[get_llm_service] = lambda f=fake: f

        first = golden_client.post(
            "/api/v1/chat", json={"session_id": None, "question": case.first_question}
        )
        if first.status_code != 200 or first.json()["not_found"]:
            failures.append((case.first_question, "first turn failed", first.json()))
            continue
        session_id = first.json()["session_id"]

        second = golden_client.post(
            "/api/v1/chat",
            json={"session_id": session_id, "question": case.follow_up_question},
        )
        body = second.json()
        if second.status_code != 200 or body["not_found"] or not body["citations"]:
            failures.append((case.follow_up_question, "follow-up failed", body))
            continue

        sections = [c.get("section") or "" for c in body["citations"]]
        if not any(case.expected_section.lower() in section.lower() for section in sections):
            failures.append(
                (case.follow_up_question, f"expected section {case.expected_section!r}", sections)
            )

    assert (
        not failures
    ), f"{len(failures)}/{len(MULTI_TURN_CASES)} multi-turn cases failed: {failures}"
