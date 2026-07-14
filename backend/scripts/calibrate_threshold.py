"""Reproducible threshold calibration (docs/threshold-calibration.md).

BAAI/bge-small-en-v1.5's raw cosine similarity for short text pairs sits
in a ~0.3-0.5 band regardless of topical relevance (anisotropy) - the
SDD's illustrative "cosine >= 0.35" default does not function as a real
anti-hallucination gate with this model. retrieval_similarity_threshold
and retrieval_high_confidence_threshold (app/core/config.py) were set
from a real measurement instead; this script reproduces that
measurement so the numbers can be re-verified whenever the fixture
document, the golden Q&A cases, or the embedding model change.

A second pass (`_groundedness_calibration`) does the same thing for the
Response Validation Agent's groundedness heuristic
(app/agents/response_validator.py, SDD 6.3.7): it measures
stopword-filtered word-set Jaccard overlap between hand-written
well-grounded/fabricated example claims and the *real* top-ranked chunk
text for the matching golden-set question, so
groundedness_reject_threshold/groundedness_comfortable_threshold are
picked from measurement too, not guessed - same discipline as the
retrieval threshold above.

Ingests the committed golden-set fixture into a throwaway temp DB/
storage/Chroma (never touches real data), runs every case from
tests/evaluation/golden_qa.py through the real retriever + ranker, and
prints per-question scores plus a suggested threshold.

Usage (from backend/):
    python scripts/calibrate_threshold.py

A second, opt-in `--live` pass sends the golden answerable questions
through the *real*, currently-configured Gemini model
(`GEMINI_MODEL_NAME`, `app/services/llm_service.py`) and scores the
real answers' groundedness against the real cited source block, using
the exact same claim-extraction/Jaccard code path as
`ResponseValidationAgent` in production. This exists because the
offline pass above only measures hand-written example claims - it
cannot tell you how a *specific model's own phrasing* scores, and that
phrasing is exactly what changes on a model swap (see
docs/threshold-calibration.md's "Model swap re-run" section: swapping
gemini-2.5-flash -> gemini-3.5-flash dropped a genuinely correct
answer's weakest score to 0.23, under the old 0.40 reject threshold).
Requires a real GEMINI_API_KEY, makes real API calls (quota cost,
non-deterministic output), and is therefore never run as part of the
default/CI invocation:

    python scripts/calibrate_threshold.py --live
"""

import argparse
import hashlib
import shutil
import statistics
import sys
import tempfile
import time
import uuid
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.agents.response_validator import (  # noqa: E402
    _contains_leak,
    _extract_claims,
    _groundedness_scores,
    _jaccard,
    _word_set,
)
from app.core.config import Settings, get_settings  # noqa: E402
from app.core.constants import NOT_FOUND_TOKEN  # noqa: E402
from app.database.repositories.documents import DocumentRepository  # noqa: E402
from app.database.seed import seed_defaults  # noqa: E402
from app.database.session import get_session_factory, init_engine  # noqa: E402
from app.rag import ranking  # noqa: E402
from app.rag.ingestion_pipeline import run_ingestion  # noqa: E402
from app.rag.prompt_builder import build_prompt  # noqa: E402
from app.rag.retriever import retrieve  # noqa: E402
from app.services.llm_service import GeminiLLMService  # noqa: E402
from app.services.storage_service import StorageService  # noqa: E402
from tests.evaluation.golden_qa import (  # noqa: E402
    ADVERSARIAL_CASES,
    ANSWERABLE_CASES,
    AdversarialTier,
)

_FIXTURE_PATH = _BACKEND_DIR / "tests" / "evaluation" / "fixtures" / "sample_hr_policy.pdf"

# (golden_qa_question, well_grounded_claim, fabricated_claim) - claims are
# hand-written; the source text they're measured against is always the
# *real*, current top-ranked chunk for that question, so this stays valid
# even if the fixture's exact wording changes.
_GROUNDEDNESS_EXAMPLES: list[tuple[str, str, str]] = [
    (
        "How many casual leave days do I get per year?",
        "Employees get twelve days of casual leave and fifteen days of earned leave each year.",
        "Employees are entitled to twenty-five days of paid sick leave every year.",
    ),
    (
        "What is the dress code on Fridays?",
        "Employees must wear business casual attire, including collared "
        "shirts, during office hours.",
        "Employees are required to wear formal suits and ties every day of the week.",
    ),
    (
        "How long is the notice period for a manager who resigns?",
        "Managerial employees must serve a notice period of sixty days when resigning.",
        "All employees must serve a notice period of ninety days regardless of role.",
    ),
    (
        "Who should I report workplace harassment to?",
        "Employees must maintain a professional, respectful workplace free from harassment.",
        "Employees who violate this policy will be fined a specific monetary penalty.",
    ),
]


def _bootstrap_settings(tmp_dir: Path) -> Settings:
    database_url = f"sqlite:///{(tmp_dir / 'calibration.db').as_posix()}"
    import os

    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    command.upgrade(cfg, "head")

    # Loads backend/.env (not disabled) so gemini_model_name/gemini_api_key/
    # gemini_timeout_seconds reflect the real, currently-configured model -
    # required for --live; harmless for the offline pass, which never reads
    # those fields. Only DB/storage/chroma are overridden, to a throwaway
    # temp location so this never touches real data.
    settings = Settings(
        _env_file=str(_BACKEND_DIR / ".env"),
        database_url=database_url,
        storage_dir=str(tmp_dir / "storage"),
        chroma_dir=str(tmp_dir / "chroma"),
    )
    init_engine(settings)
    return settings


def _ingest_fixture(settings: Settings) -> uuid.UUID:
    content = _FIXTURE_PATH.read_bytes()
    db = get_session_factory()()
    try:
        seed_defaults(db, settings)
        tenant_id = uuid.UUID(settings.default_tenant_id)
        user_id = uuid.UUID(settings.default_user_id)

        storage = StorageService(settings)
        storage_path = f"uploads/{tenant_id}/sample_hr_policy.pdf"
        storage.save(storage_path, content)

        document = DocumentRepository(db).create(
            tenant_id=tenant_id,
            uploaded_by=user_id,
            file_name="sample_hr_policy.pdf",
            display_name="sample_hr_policy.pdf",
            storage_path=storage_path,
            content_hash=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
        )
        document_id = document.id
    finally:
        db.close()

    run_ingestion(document_id, tenant_id, settings=settings)
    return tenant_id


def _top_score(question: str, *, tenant_id: uuid.UUID, settings: Settings) -> float | None:
    results = retrieve(question, tenant_id=tenant_id, settings=settings)
    return results[0].score if results else None


def _groundedness_calibration(*, tenant_id: uuid.UUID, settings: Settings) -> None:
    print(
        "\n--- Response validation groundedness (stopword-filtered Jaccard) ---\n"
        f"Current settings: groundedness_reject_threshold="
        f"{settings.groundedness_reject_threshold}, "
        f"groundedness_comfortable_threshold="
        f"{settings.groundedness_comfortable_threshold}\n"
    )
    grounded_scores = []
    fabricated_scores = []
    for question, grounded_claim, fabricated_claim in _GROUNDEDNESS_EXAMPLES:
        chunks = retrieve(question, tenant_id=tenant_id, settings=settings)
        blocks = ranking.rank_chunks(chunks, settings=settings)
        source_words = _word_set(blocks[0].text)
        grounded_score = _jaccard(_word_set(grounded_claim), source_words)
        fabricated_score = _jaccard(_word_set(fabricated_claim), source_words)
        grounded_scores.append(grounded_score)
        fabricated_scores.append(fabricated_score)
        print(f"grounded={grounded_score:.3f}  fabricated={fabricated_score:.3f}  {question}")

    min_grounded = min(grounded_scores)
    max_fabricated = max(fabricated_scores)
    print(
        f"\nmin grounded score:   {min_grounded:.4f}\n"
        f"max fabricated score: {max_fabricated:.4f}\n"
        f"midpoint: {round((min_grounded + max_fabricated) / 2, 2)}"
    )


def _live_groundedness_calibration(
    *, tenant_id: uuid.UUID, settings: Settings, delay_seconds: float
) -> None:
    print(
        "\n--- LIVE groundedness calibration (real Gemini answers) ---\n"
        f"model={settings.gemini_model_name}\n"
        f"Current settings: groundedness_reject_threshold="
        f"{settings.groundedness_reject_threshold}, "
        f"groundedness_comfortable_threshold="
        f"{settings.groundedness_comfortable_threshold}\n"
    )
    if not settings.gemini_api_key.get_secret_value():
        print("Skipped: GEMINI_API_KEY is not set. --live requires a real key.")
        return

    llm = GeminiLLMService(settings)
    weakest_scores: list[float] = []
    false_refusals: list[str] = []
    errors: list[tuple[str, str]] = []

    for index, case in enumerate(ANSWERABLE_CASES):
        # Free-tier Gemini quota is bursty, not just RPM-shaped: back-to-back
        # calls exhausted it within ~5 requests during real calibration runs
        # (LlmQuotaExceededError), and it took over 90s of *not* calling to
        # recover. A fixed inter-call delay is a crude fix, but the
        # alternative - burning quota on retries that just re-trip the same
        # limit - is worse for a script whose entire job is measuring the
        # real model.
        if index > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)

        chunks = retrieve(case.question, tenant_id=tenant_id, settings=settings)
        blocks = ranking.rank_chunks(chunks, settings=settings)
        built = build_prompt(case.question, blocks, settings=settings)

        try:
            result = llm.generate(built.text)
        except Exception as exc:  # noqa: BLE001 - one live-call failure shouldn't abort the run
            errors.append((case.question, repr(exc)))
            print(f"ERROR calling model  {case.question}: {exc!r}")
            continue

        answer = result.text.strip()
        if answer == NOT_FOUND_TOKEN:
            false_refusals.append(case.question)
            print(f"FALSE REFUSAL (NOT_FOUND on an answerable question)  {case.question}")
            continue
        if _contains_leak(answer):
            print(f"LEAK DETECTED  {case.question}")
            continue

        claims = _extract_claims(answer)
        scores = _groundedness_scores(claims, blocks)
        if not scores:
            print(f"no [S#]-tagged claims found, skipping  {case.question}")
            continue

        weakest = min(scores)
        weakest_scores.append(weakest)
        print(f"weakest={weakest:.4f}  claims={len(scores)}  {case.question}")

    if not weakest_scores:
        print("\nNo scorable live answers collected - cannot suggest thresholds.")
        return

    minimum = min(weakest_scores)
    median = statistics.median(weakest_scores)
    maximum = max(weakest_scores)
    print(
        f"\nlive grounded weakest-score distribution over {len(weakest_scores)} "
        f"answerable case(s): min={minimum:.4f}  median={median:.4f}  max={maximum:.4f}\n"
        f"false refusals: {len(false_refusals)}/{len(ANSWERABLE_CASES)}  errors: {len(errors)}\n"
        "\nPick groundedness_reject_threshold below this real floor (with margin,\n"
        "biased toward not rejecting genuine answers - see "
        "docs/threshold-calibration.md); pick groundedness_comfortable_threshold\n"
        "at or just below the real floor so genuinely-grounded-but-terser live\n"
        "answers still get full confidence rather than being downgraded."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Also send the golden answerable questions through the real, "
            "currently-configured Gemini model and score the real answers' "
            "groundedness. Requires GEMINI_API_KEY. Makes real API calls "
            "(quota cost, non-deterministic) - off by default."
        ),
    )
    parser.add_argument(
        "--live-delay-seconds",
        type=float,
        default=25.0,
        help=(
            "Delay between --live calls to stay under free-tier burst quota "
            "(default 25s; observed rate-limit recovery took >90s after a "
            "5-call burst during real calibration - lower this only if "
            "using a higher-quota key)."
        ),
    )
    args = parser.parse_args()

    tmp = tempfile.mkdtemp()
    try:
        settings = _bootstrap_settings(Path(tmp))
        tenant_id = _ingest_fixture(settings)

        print(f"Current settings: retrieval_similarity_threshold="
              f"{settings.retrieval_similarity_threshold}, "
              f"retrieval_high_confidence_threshold="
              f"{settings.retrieval_high_confidence_threshold}\n")

        print("--- Answerable cases (must clear the threshold) ---")
        answerable_scores = []
        for case in ANSWERABLE_CASES:
            score = _top_score(case.question, tenant_id=tenant_id, settings=settings)
            answerable_scores.append(score)
            survives = score is not None and score >= settings.retrieval_similarity_threshold
            print(f"{score:.4f}  survives={survives}  {case.question}")

        print("\n--- Adversarial: off_topic (must be rejected by the real gate) ---")
        off_topic_scores = []
        for case in ADVERSARIAL_CASES:
            if case.tier is not AdversarialTier.OFF_TOPIC:
                continue
            score = _top_score(case.question, tenant_id=tenant_id, settings=settings)
            off_topic_scores.append(score)
            survives = score is not None and score >= settings.retrieval_similarity_threshold
            print(f"{score:.4f}  survives={survives}  {case.question}")

        print("\n--- Adversarial: topically_adjacent (expected to clear the gate) ---")
        for case in ADVERSARIAL_CASES:
            if case.tier is not AdversarialTier.TOPICALLY_ADJACENT:
                continue
            score = _top_score(case.question, tenant_id=tenant_id, settings=settings)
            survives = score is not None and score >= settings.retrieval_similarity_threshold
            print(f"{score:.4f}  survives={survives}  {case.question}")

        min_answerable = min(answerable_scores)
        max_off_topic = max(off_topic_scores)
        suggested = round((min_answerable + max_off_topic) / 2, 2)
        print(
            f"\nmin answerable score: {min_answerable:.4f}\n"
            f"max off-topic score:  {max_off_topic:.4f}\n"
            f"midpoint (suggested retrieval_similarity_threshold): {suggested}"
        )

        _groundedness_calibration(tenant_id=tenant_id, settings=settings)

        if args.live:
            _live_groundedness_calibration(
                tenant_id=tenant_id, settings=settings, delay_seconds=args.live_delay_seconds
            )
    finally:
        # ChromaDB keeps file handles open briefly after use on Windows;
        # best-effort cleanup, not part of the calibration itself.
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
