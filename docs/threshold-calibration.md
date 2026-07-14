# Retrieval Threshold Calibration

## Summary

`retrieval_similarity_threshold` (SDD §6.3.4/§7.2 Stage 8, the primary
anti-hallucination gate) is **0.50**, and `retrieval_high_confidence_threshold`
(§6.3.8 confidence labeling) is **0.65** — both set from a real
measurement against the golden-set fixture, superseding the SDD's
illustrative "cosine ≥ 0.35" text.

## Why 0.35 doesn't work

`BAAI/bge-small-en-v1.5`'s raw cosine similarity for short text pairs
sits in a roughly 0.3–0.5 band **regardless of topical relevance**. This
is a documented property of sentence-embedding models sometimes called
anisotropy: embeddings for short, generic-structure sentences cluster
in a narrow cone of the embedding space, so cosine similarity is a much
better *relative* ranking signal (which of these 8 chunks is most
relevant?) than an *absolute* one (is this chunk relevant at all?).

Measured directly (`scripts/calibrate_threshold.py`) against a 5-topic,
5-chunk fixture: genuinely unrelated content — "What is the capital of
France?", SQL injection strings, French text, random gibberish, biology
facts — scored between 0.30 and 0.52 against every chunk in the corpus.
At the SDD's suggested 0.35, almost none of that is rejected. This
isn't a quirk of a small corpus; a near-identical floor showed up in an
even smaller single-chunk experiment first (Phase 5 Module 6). It's a
property of the model and short-text inputs, not of corpus size.

## The measurement behind 0.50 / 0.65

Run via `scripts/calibrate_threshold.py` against
`tests/evaluation/fixtures/sample_hr_policy.pdf` (5 topics: Leave
Policy, Dress Code, Travel and Reimbursement, Notice Period, Code of
Conduct) and the 20-case set in `tests/evaluation/golden_qa.py`:

| Case type | Score range |
|---|---|
| Answerable (on-topic) questions | 0.60 – 0.85 |
| Adversarial, off-topic | 0.30 – 0.44 |
| Adversarial, topically-adjacent-but-absent | 0.61 – 0.72 |

`retrieval_similarity_threshold = 0.50` sits below the answerable floor
(0.60) with margin against false refusals, and above the off-topic
ceiling (0.44) with margin against false positives. The exact midpoint
of the measured gap is 0.52; 0.50 was chosen to bias slightly toward
not refusing genuine answers.

`retrieval_high_confidence_threshold = 0.65` sits inside the answerable
range (0.60–0.85), giving a meaningful high/low confidence split
instead of being a no-op at or below the gate itself (the old default
of 0.5 was *below* the new similarity threshold, meaning every answer
that passed the gate at all would trivially also count as "high
confidence" — not a meaningful signal).

## A known limitation: topically-adjacent questions

The "topically-adjacent" tier (e.g. asking about maternity leave when
the fixture only documents casual/earned leave) scores *above* the
threshold — 0.61–0.72, well within the answerable range — because the
question genuinely shares vocabulary and topic with real content. These
reach the LLM and depend entirely on the model correctly recognizing
that its sources don't actually answer the specific question asked and
emitting the `NOT_FOUND` token.

This is not a retrieval problem to fix with a better threshold; no
absolute cosine cutoff can distinguish "same topic, different specific
claim" from "same topic, matching claim" — that's a job for grounded
generation plus validation, which is exactly why the pipeline has both
gates (SDD §11.3's "double-gate": pre-LLM threshold + post-LLM
validation). `tests/evaluation/test_golden_set.py` is explicit about
this: it configures the fake LLM to correctly emit `NOT_FOUND` for
these cases (verifying the citation/refusal-normalization plumbing
works), but documents plainly that this does not prove real Gemini
model compliance — that requires the documented live run.

A cross-encoder reranker (SDD §12.2) would improve precision on exactly
this class of case and is the noted future seam; it's out of scope for
Phase 5.

## Reproducing this

```
cd backend
python scripts/calibrate_threshold.py
```

Re-run whenever:
- The embedding model changes (Appendix A / ADR-002 model swap).
- The golden-set fixture (`tests/evaluation/fixtures/sample_hr_policy.pdf`)
  or its Q&A cases (`tests/evaluation/golden_qa.py`) change.
- The measured gap looks like it's closing (i.e. answerable scores
  trending down or off-topic scores trending up) — re-tune the two
  thresholds in `app/core/config.py` and `.env.example` from the new
  numbers.

## Response validation groundedness (Phase 6)

`groundedness_reject_threshold` (**0.10**, previously 0.40) and
`groundedness_comfortable_threshold` (**0.13**, previously 0.55) — the
Response Validation Agent's groundedness heuristic (SDD §6.3.7,
`app/agents/response_validator.py`) — are calibrated the same way and
for the same reason: an assumed cutoff can't be trusted without
measuring it against this specific heuristic and this specific model's
output style. **These numbers were substantially revised in the "Model
swap re-run" below — the 0.40/0.55 history is kept here for context.**

The heuristic itself is deliberately different from the retrieval
threshold: not cosine similarity, but stopword-filtered word-set
Jaccard overlap between a claim (the answer text up to and including
its `[S#]` tag) and the real source block it cites. This is a lexical
check, not a semantic-embedding one, so it doesn't inherit the
retrieval threshold's anisotropy problem — but it needed its own
measurement, not an assumed value, for the same underlying reason
(SDD §6.3.7's suggested Jaccard cutoff is illustrative, not calibrated).

`scripts/calibrate_threshold.py`'s offline pass measures four
hand-written (well-grounded claim, fabricated claim) pairs against the
*real, current* top-ranked source block for four golden-set questions
(ingesting the same fixture, running the real retriever + ranker — the
claims are hardcoded, but the source text they're measured against
always reflects the fixture as it exists today):

| Case type | Score range (original, truncated fixture) | Score range (current, full fixture) |
|---|---|---|
| Well-grounded paraphrase | 0.57 – 0.67 | 0.159 – 0.220 |
| Fabricated (same topic, absent fact) | 0.05 – 0.31 | 0.061 – 0.135 |

The "current" column is lower across the board, and the gap between
the two rows is much narrower — see "Model swap re-run" for why (the
fixture fix alone explains most of this drop; it isn't about the model).

Re-run alongside the retrieval-threshold calibration above whenever the
fixture, golden set, or embedding model changes; also re-run if the
answer prompt template (`app/prompts/`) changes enough to plausibly
shift how the model phrases cited claims.

## Model swap re-run (2026-07-11): gemini-2.5-flash → gemini-3.5-flash

**Trigger.** `GEMINI_MODEL_NAME` was switched to `gemini-3.5-flash`
after `gemini-2.5-flash` was retired (real calls started 404ing). The
new model's phrasing style tripped the groundedness reject gate in
production on a genuinely correctly-answered question
(`weakest_score=0.23` vs. the old `0.40` threshold) — this is exactly
the documented re-run trigger from the section above ("the measured gap
looks like it's closing").

**A second, unrelated bug surfaced during recalibration.** Before any
live-model measurement could be trusted, `scripts/calibrate_threshold.py`
was extended with a `--live` mode (see below) that sends the golden
answerable questions through the real, currently-configured model.
Running it turned up 8/10 false `NOT_FOUND` refusals — far more than
model-phrasing variance could explain. Investigation traced this to
`tests/evaluation/fixtures/sample_hr_policy.pdf` itself: every page's
extracted text was truncated mid-sentence (e.g. "...fifteen days of
earned leave per calendar year. **Casu**", "...hotel **accomm**"),
confirmed by extracting the committed PDF directly with PyMuPDF,
bypassing our own ingestion pipeline entirely. Several
`ANSWERABLE_CASES` questions (e.g. "Can I carry forward my earned
leave?") asked about facts that had simply never survived into the
committed fixture — the real model was correctly refusing to answer
from a source that didn't contain the answer. This had been invisible
because `FakeLLMService`'s default double echoes the (possibly
truncated) source text verbatim, so no offline test ever exercised
whether the truncated text was semantically complete.

**Fix:** `scripts/generate_golden_fixture.py` (new) rebuilds the
fixture with complete paragraphs for all five topics, still using
PyMuPDF, still preserving every fact `ANSWERABLE_CASES` needs and
deliberately omitting every fact the `TOPICALLY_ADJACENT` adversarial
tier depends on being absent (see that script's docstring for the
full per-topic breakdown). Re-run it if the fixture ever needs
regenerating:

```
cd backend
python scripts/generate_golden_fixture.py
```

**Effect on the retrieval-threshold numbers (table near the top of this
doc):** answerable scores rose to 0.74–0.85 and off-topic scores rose
slightly to 0.37–0.47 (fuller, more distinctive text per chunk).
`retrieval_similarity_threshold = 0.50` remains comfortably valid with
even more margin than before — **not changed** by this re-run.

**Effect on the groundedness numbers:** this is where it matters. Full
paragraphs have a much larger vocabulary than the old ~130-character
truncated chunks, which pulls every Jaccard score down (larger union,
same claim size) — this alone accounts for most of the drop in the
offline hand-written table above, independent of which LLM is used.

**Live measurement (`--live`).** New `--live` flag on
`scripts/calibrate_threshold.py` sends each of the 10
`ANSWERABLE_CASES` questions through the real, currently-configured
`GeminiLLMService` (real retrieval, real ranking, real prompt, real
answer) and scores the real answer's weakest claim exactly the way
`ResponseValidationAgent` does in production — this is the only way to
measure a specific model's actual phrasing style, which is precisely
what changes on a model swap:

```
cd backend
python scripts/calibrate_threshold.py --live
```

Measured against `gemini-3.5-flash` and the fixed fixture, 10/10
answerable cases answered correctly (0 false refusals, 0 errors):

| | weakest per-answer Jaccard score |
|---|---|
| min | 0.1333 |
| median | 0.2299 |
| max | 0.3800 |

**New thresholds.** `groundedness_reject_threshold = 0.10` sits with
margin below the real measured floor (0.1333) — biased toward not
rejecting genuine live answers, same philosophy as the original
calibration. `groundedness_comfortable_threshold = 0.13` sits just
under the measured floor, so claims between the two are downgraded to
LOW confidence rather than rejected outright.

**Known limitation this re-run surfaced.** The real grounded floor
(0.1333) now sits *below* the hand-written fabricated ceiling from the
offline pass (0.135) — the two distributions have nearly collapsed
together. A reject threshold that reliably clears the real grounded
floor can no longer reliably catch all fabricated claims via this
heuristic alone; 3 of the 4 hand-written fabricated examples
(0.106–0.135) now score *above* `groundedness_reject_threshold = 0.10`
and would not be caught by this gate. This isn't a mistake in the
threshold choice — any threshold that avoids false-rejecting real
`gemini-3.5-flash` answers has to sit in this same collapsed region.
It means this heuristic is now a weaker independent signal than it was
against `gemini-2.5-flash`, and the system leans more on its other
anti-hallucination layers for this class of case: the pre-LLM
`retrieval_similarity_threshold` gate, and Citation Agent's `[S#]`
tag-validity check (SDD's "double-gate" design, §11.3). A cross-encoder
reranker or a semantic (embedding-based) groundedness check, rather
than lexical Jaccard, is the natural fix if this heuristic needs to
regain precision — out of scope for this re-run.

**Free-tier rate limits.** Running `--live` against a free-tier API key
hit `LlmQuotaExceededError` after ~5 back-to-back calls, and recovery
took over 90 seconds of not calling before a probe call succeeded
again — this is bursty, not a simple per-minute budget that a short
backoff clears. `--live` now sleeps `--live-delay-seconds` (default 25s)
between calls to stay under it; lower this only with a higher-quota key.

**Timeout.** Real `gemini-3.5-flash` calls were observed taking
19–30 seconds (against the old 20s `GEMINI_TIMEOUT_SECONDS` default —
the 19.2s production call that motivated this whole re-run had almost
no margin). `gemini_timeout_seconds` default raised to **45.0**.

**Re-run this whenever:** the configured Gemini model changes (as
happened here), the fixture or golden set changes, or the answer
prompt template changes enough to plausibly shift phrasing.
