# Enterprise HR Policy AI Assistant

Read docs/sdd.md before making architectural decisions. It is the source of truth.

## Rules
- Follow the folder structure in SDD Section 9 exactly
- Layering: api → agents → services → infrastructure. Agents never touch
  external systems directly, only through services/
- All config via pydantic-settings; no hardcoded values or secrets
- Prompts live as files in app/prompts/, never inline strings
- Python: type hints everywhere, Pydantic models for all API schemas
- Embeddings: BAAI/bge-small-en-v1.5 local; LLM: Gemini via LLMService only
- Every new module gets unit tests in backend/tests/
- Do not add features beyond the current phase's scope
