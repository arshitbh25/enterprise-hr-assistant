"""Retriever Agent (SDD Section 6.3.3) - thin wrapper.

Confirms the tenant has at least one READY document (SDD's "empty
index" failure case), then delegates to `app.rag.retriever.retrieve()`
(Phase 5, unchanged) to embed the query and run the tenant-filtered
ChromaDB search.

Input: `context.standalone_query` (falls back to `raw_question` if
Query Understanding hasn't set it - e.g. when this agent is exercised
in isolation before Module 4 exists). Output: `context.retrieved_chunks`.

Communication: Query Understanding Agent -> this agent -> Context
Ranking Agent.

Failure cases: no READY documents -> `NoDocumentsIndexedError` (409,
relocated unchanged from Phase 5's `chat.py`); a ChromaDB error is
retried once and then raises `VectorStoreUnavailableError` (503) -
already handled inside `app.rag.retriever.retrieve()` itself, unchanged.
"""

from app.agents.base import QueryContext, agent_stage
from app.core.config import Settings
from app.core.constants import DocumentStatus
from app.core.exceptions import NoDocumentsIndexedError
from app.database.repositories.documents import DocumentRepository
from app.rag import retriever as rag_retriever


class RetrieverAgent:
    name = "retriever"

    def __init__(self, *, document_repo: DocumentRepository, settings: Settings) -> None:
        self._document_repo = document_repo
        self._settings = settings

    def run(self, context: QueryContext) -> QueryContext:
        with agent_stage(context, self.name):
            _, ready_document_count = self._document_repo.list(
                context.tenant_id, status=DocumentStatus.READY, page=1, page_size=1
            )
            if ready_document_count == 0:
                raise NoDocumentsIndexedError()

            query = context.standalone_query or context.raw_question
            context.retrieved_chunks = rag_retriever.retrieve(
                query, tenant_id=context.tenant_id, settings=self._settings
            )
        return context
