# Chunking Strategy Decision

## Context

Stage 3 of the RAG pipeline (SDD §7.2) turns cleaned, per-page PDF text
into the units that get embedded, retrieved, and cited. The chunking
strategy is one of the highest-leverage decisions in the whole system:
retrieval quality, citation precision, and the anti-hallucination
guarantee (SDD §1.2 — "never fabricate") all depend on a chunk being a
coherent, self-contained unit of policy meaning. A bad chunk boundary is
a silent failure mode: the system doesn't error, it just retrieves a
clause without its qualifier and answers confidently wrong.

## Candidates Considered

### 1. Fixed-size chunking

Split the raw text into fixed windows (e.g. every 500 characters or 300
tokens), usually with a fixed overlap, with no awareness of sentence,
paragraph, or section structure.

- **Strengths**: trivial to implement, fastest, fully deterministic,
  zero dependency on document structure.
- **Fatal weakness for HR policy text**: window boundaries fall wherever
  the character count runs out, with no regard for meaning. HR clauses
  routinely depend on a trailing qualifier — "Employees may carry
  forward up to 10 leave days, *except employees on probation*." A
  fixed window can easily end mid-clause, so the qualifier lands in the
  next chunk and is never retrieved alongside the entitlement it
  modifies. This directly undermines the groundedness guarantee (SDD
  §1.2, §6.3.4): the retrieved chunk looks complete and confident but is
  factually incomplete.

### 2. Recursive character/token splitting (generic, structure-blind)

The common "LangChain-style" `RecursiveCharacterTextSplitter` approach:
try to split on the largest available separator first (double newline →
single newline → sentence → word), recursing until each piece fits the
target size, with overlap between adjacent pieces.

- **Strengths**: a real improvement over fixed-size — it respects
  paragraph and sentence boundaries, so it rarely cuts a sentence in
  half.
- **Weakness**: it has no concept of the *document's* structure. It
  treats the entire PDF as one undifferentiated stream of paragraphs, so
  nothing stops it from packing the tail of one section ("Leave
  Accrual") and the head of the next ("Leave Forfeiture") into the same
  chunk purely because they happen to fall within the token budget back
  to back. That merges two distinct policy topics into one retrieval
  unit, hurting both retrieval precision (the chunk half-matches two
  different questions) and citation clarity (which section does this
  answer actually come from?).

### 3. Structure-aware recursive splitting — **chosen (SDD §7.2 Stage 3)**

Split first on detected section headings (from font-size/bold heuristics
in Stage 2), then recursively within each section: paragraph → sentence
→ word, packed greedily to a ~600-token target with ~100-token overlap.
Chunks never cross a section boundary.

- **Why it wins for this document type**: HR policies are already
  authored as self-contained sections under headings ("Leave Accrual and
  Lapse Rules", "Notice Period", "POSH Complaint Procedure"). Splitting
  on headings first means chunk boundaries align with the document
  author's own semantic boundaries, not an arbitrary character count.
  This is also exactly what makes citations meaningful: "see
  Leave_Policy.pdf, *Leave Accrual and Lapse Rules*, p.12" is a
  verifiable pointer an employee (or auditor) can actually use, per
  FR-Q04 and the trust requirement in SDD §1.2.
- **Why ~600 tokens / 100 overlap specifically**: 600 tokens is large
  enough to keep a full clause plus its qualifiers together (small
  chunks orphan conditions like "except employees on probation" into a
  separate, unretrieved chunk), while 4 retrieved chunks then stay
  within a ~2,000-token prompt context budget (SDD §6.3.4, §7.2 Stage
  9) — small enough to keep generation fast and cheap on a free-tier
  LLM. The 100-token overlap exists so that an answer whose evidence
  happens to sit right at a chunk seam is still fully present in at
  least one retrieved chunk, rather than being split exactly in half
  across two chunks that individually look weakly relevant.
- **Cost**: heading detection is heuristic (font-size/bold spans, SDD
  §7.2 Stage 2) and not always reliable — addressed below under
  graceful degradation.

### 4. Semantic / embedding-based chunking

Compute sentence-level embeddings and cut wherever the cosine similarity
between adjacent sentences drops below a threshold — chunk boundaries
follow topic shifts detected by the embedding model itself, not
character counts or formatting.

- **Strengths**: in principle the most semantically coherent boundaries,
  since it directly measures "does this still belong with the previous
  sentence" rather than inferring it from formatting.
- **Why not chosen for v1**:
  1. **Ordering dependency**: it requires the embedding model to be
     available and warm at *ingestion* time. In this codebase embeddings
     are Phase 4 (`app/embeddings/` is intentionally empty in Phase 3);
     making Stage 3 depend on Stage 5 inverts the pipeline's layering.
  2. **Cost/latency**: embedding every sentence just to decide where to
     cut is meaningfully more compute than a formatting heuristic, for
     marginal benefit on documents that are already well-structured by
     their authors (HR policies, unlike scraped web text, are not
     unstructured prose that benefits most from semantic segmentation).
  3. **Auditability**: SDD ADR-003 requires deterministic, auditable
     agent/pipeline behavior. A similarity-threshold cut point is a
     continuous, model-dependent decision that shifts if the embedding
     model is ever swapped (SDD §14 leaves this door open) — chunk
     boundaries would silently change on a model upgrade. Heading-based
     splitting is stable, inspectable, and independent of any model
     version.
  4. It's the natural **Phase-12-style enhancement**, not a v1
     requirement — it could later run as a refinement pass *within* an
     already-structure-aware section, not as a replacement for it.

## Decision

**Structure-aware recursive chunking**, per SDD §7.2 Stage 3, at ~600
target tokens / 100-token overlap, sections first then
paragraph→sentence→word.

## Graceful Degradation

Heading detection is a heuristic (relative font size / bold spans) and
will occasionally find zero headings — e.g. a policy PDF authored with
uniform formatting throughout. In that case the chunker treats the
entire document as a single implicit section and falls back to plain
recursive paragraph→sentence packing (equivalent to Candidate 2) for
that document only. This is a deliberate, silent fallback rather than a
failure: it still produces usable chunks, just without the
section-boundary guarantee — an acceptable degradation for the rare
poorly-formatted document, versus failing ingestion outright.
