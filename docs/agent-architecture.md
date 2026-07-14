# Agent Architecture (As-Built)

## Context

SDD §6 specifies the agent architecture at the design level: nine named
agents (§6.3.1–§6.3.8, plus Memory §6.3.9 and Logging §6.3.10), a
sequence diagram (§6.2), and an error doctrine (§6.4: "fail closed on
truthfulness, fail soft on convenience"). This document records how
that design was actually implemented (Modules 3–7) and where the real
code refined or diverged from the SDD's illustrative text — the same
purpose [chunking-decision.md](chunking-decision.md) and
[threshold-calibration.md](threshold-calibration.md) serve for their
respective areas. Read this alongside `app/agents/base.py` and
`app/agents/orchestrator.py`, which remain the source of truth for the
exact contract; this doc explains the *why* behind their shape.

## The `QueryContext` Contract

Every agent reads and writes one shared, mutable Pydantic model
(`app.agents.base.QueryContext`) rather than passing narrower
per-agent arguments — SDD §6.1's "typed, append-only" shared state. In
practice "append-only" is a per-agent discipline (each agent only
writes the field(s) it owns), not a Pydantic-enforced constraint.

| Field group | Written by | Notes |
|---|---|---|
| `request_id`, `tenant_id`, `user_id`, `raw_question` | `chat.py`, before the pipeline runs | Identity + the literal request body |
| `session_id`, `suspicious` | `UserQueryAgent` | `session_id` doubles as input (caller's requested session, `None` = create) and output (resolved id) |
| `memory_turns`, `memory_summary` | `MemoryReadAgent` | Empty/`None` on any read failure (fail soft) |
| `standalone_query`, `scope`, `clarification_needed` | `QueryUnderstandingAgent` | `scope` off-topic/greeting sets `short_circuit_reason` directly |
| `retrieved_chunks` | `RetrieverAgent` | |
| `ranked_blocks` | `ContextRankingAgent` | Empty result is anti-hallucination gate #1 — sets `short_circuit_reason` |
| `prompt_text`, `prompt_blocks` | `PromptConstructionAgent` | `prompt_blocks` may be a trimmed subset of `ranked_blocks` |
| `draft_answer`, `llm_usage` | `LLMAgent` | |
| `validation_verdict`, `force_low_confidence` | `ResponseValidationAgent` | Anti-hallucination gate #2. `force_low_confidence` is a *cap*, not a value — see below |
| `citations` | `CitationAgent` | |
| `final_answer`, `confidence`, `not_found` | Whichever agent finalizes the turn (Context Ranking, Query Understanding, Response Validation, or Citation) | The route never computes these itself |
| `assistant_message_id` | `MemoryWriteAgent` | Added Module 7 so `chat.py` can return the persisted message's real id without a second DB read |
| `short_circuit_reason` | Any agent | Orchestrator checks this after every stage |
| `stage_timings`, `stage_statuses` | `agent_stage()` (every agent, via the context manager it wraps its body in) | The audit record — see Logging below |

## Pipeline Sequence (as-built)

`app.agents.orchestrator.build_pipeline()` assembles the stoppable
sequence in exactly this order (SDD §6.2):

1. `UserQueryAgent` (§6.3.1) — sanitize, resolve/create session, flag injection patterns
2. `MemoryReadAgent` (§6.3.9 read path) — last N turns + rolling summary
3. `QueryUnderstandingAgent` (§6.3.2) — scope classification, follow-up rewrite, acronym expansion
4. `RetrieverAgent` (§6.3.3) — embed + ChromaDB top-k, tenant-filtered
5. `ContextRankingAgent` (§6.3.4) — threshold/dedupe/MMR/merge → top 4, **or NOT_FOUND**
6. `PromptConstructionAgent` (§6.3.5) — assemble the versioned template, now including conversation history (Module 7)
7. `LLMAgent` (§6.3.6) — the sole Gemini call for generation
8. `ResponseValidationAgent` (§6.3.7) — groundedness heuristic + leak check, **or NOT_FOUND**
9. `CitationAgent` (§6.3.8) — resolve `[S#]` tags, finalize the answer, **or NOT_FOUND**

`MemoryWriteAgent` (§6.3.9 write path) is deliberately **not** in this
list. `build_memory_write_agent()` builds it separately, and `chat.py`
runs it unconditionally after `run_pipeline()` returns — even a turn
that short-circuited at step 3, 5, or 8 still gets persisted with its
refusal answer, matching the SDD's own requirement that a correct
refusal is a successful, logged turn (FR-Q03), not a dropped one.

## Control-Flow Doctrine

`run_pipeline()` (`app/agents/orchestrator.py`) is intentionally
mechanical: run each agent, check `context.short_circuit_reason` after
every stage, stop if set. No retry layer lives here — `LLMService`
already owns its own backoff/circuit-breaker (SDD §6.3.6), and a
second retry layer at the orchestrator level would double that logic
for no benefit.

Two distinct outcomes an agent can produce, per SDD §6.4:

- **Fail closed** (truthfulness at risk): the agent sets
  `short_circuit_reason` *and* writes the standard NOT_FOUND answer
  directly onto the context itself — the orchestrator doesn't know
  what NOT_FOUND means, it only knows to stop. `ContextRankingAgent`,
  `QueryUnderstandingAgent` (off-topic/greeting), and
  `ResponseValidationAgent` all do this.
- **Fail soft** (convenience at risk): the agent catches its own
  exception, marks `context.stage_statuses[name] = "degraded"`, and
  returns normally — the pipeline never sees a `short_circuit_reason`.
  `MemoryReadAgent` (DB read failure → proceed memory-less) and
  `QueryUnderstandingAgent`'s own rewrite-call failure (→ fall back to
  the raw question) are the two examples in the current roster.

A **genuine exception** (a real bug, or an `LLMService`/repository
error that isn't one of the two cases above — e.g.
`NoDocumentsIndexedError`, `LlmUnavailableError`) propagates straight
out of `run_pipeline()` unchanged and is mapped to its HTTP status by
the existing global `DomainError` handler, exactly as it was before
any of this agent wiring existed.

## Logging: `agent_stage()`, not a Logging Agent class

SDD §6.3.10 describes a "Logging Agent" as one of ten agents in the
roster. In the implementation it isn't a class with a `.run()` method
— it's `app.agents.base.agent_stage()`, a context manager every other
agent wraps its own body in. Each use records duration into
`context.stage_timings[name]`, defaults `stage_statuses[name]` to
`"ok"` (an agent that fail-softs overwrites this to `"degraded"`
itself before returning), and emits one structured log event per
stage. This was a deliberate simplification over a tenth pipeline
entry: logging is cross-cutting by nature, and a context manager gives
every agent the instrumentation "for free" without needing to
sequence a separate agent around each one.

## Refinements vs. the Original SDD §6 Text

- **Citation Agent's fail-closed rule is stricter than §6.3.8's literal
  text.** The SDD describes dropping just the offending claim's tag on
  a citation-integrity problem; the implementation (`app/rag/citations.py`,
  predates the agent wrapper) downgrades the *whole* answer to
  NOT_FOUND on any invalid tag reference or zero-citation factual
  answer — a deliberate, explicit simplification per an earlier
  session's instruction, kept because it's strictly more conservative
  (fail-closed) than the SDD's version.
- **`force_low_confidence` is a cap, not an assignment.** Response
  Validation sets it on borderline (but passing) groundedness; Citation
  Agent must read and respect it — downgrading `HIGH` to `LOW` — rather
  than blindly overwriting confidence with its own retrieval-score-only
  computation. Getting this contract backwards (Citation Agent silently
  clobbering the flag) was the exact bug caught and fixed in Module 6's
  review.
- **Memory is two agent classes, not one.** SDD §6.3.9 describes a
  single "Conversation Memory Agent" with read and write
  responsibilities. Since those responsibilities land at two genuinely
  different points in the sequence (early read, late unconditional
  write), the implementation splits them into `MemoryReadAgent` and
  `MemoryWriteAgent` sharing one module (`app/agents/memory.py`) rather
  than one class run twice with internal mode-switching.
- **Conversation history in the prompt is a Module 7 addition.**
  §6.3.5 always specified "condensed conversation history" as part of
  the prompt, but it didn't land until history had somewhere real to
  come from (Module 7, once Memory was wired into the live pipeline).
  It's rendered in a `<history>` tag with the same anti-injection
  data/instruction treatment as `<source>` (`app/prompts/answer_v1.txt`
  rule 4), and is the *first* thing trimmed if the prompt is still over
  budget after dropping the lowest-ranked source block — sources always
  win over memory, since a grounded answer needs its evidence more than
  its history.

## Known Limitations / Future Seams

- **Transport is in-process only** (SDD §6.4): agents are plain
  function calls sharing one context object. The typed contract means
  a future queue/service boundary between agents is a wiring change,
  not a rewrite — nothing here assumes same-process execution beyond
  the wiring itself.
- **Response Validation's groundedness heuristic is lexical
  (Jaccard), not semantic** — see
  [threshold-calibration.md](threshold-calibration.md) for why, and
  its measured thresholds.
- **Rewrite/summary LLM calls have no independent retry budget** —
  they go through the same `LLMService` as the main generation call,
  so a quota exhaustion affects both equally by design (SDD doesn't
  call for tiering these).

## Extending the Pipeline

To add a new agent: implement the `Agent` protocol (`name: str`,
`run(context) -> context`, body wrapped in `agent_stage()`), give it a
module docstring in the house style (SDD reference, responsibility,
input/output, communication, failure cases — the style already present
in every existing agent file), register it in `build_pipeline()` at
the correct position, and add unit tests in
`backend/tests/unit/test_agents_*.py` covering both its happy path and
every documented failure case.
