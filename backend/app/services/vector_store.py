"""Vector store adapter (SDD Section 7.2 Stage 6, ADR-009).

Ports & adapters: VectorStoreService is the interface, ChromaVectorStore
the concrete adapter - a future vector-DB swap (SDD Section 3.2 scale
path) touches only this module. Constructed fresh per call site (like
StorageService), not a singleton: PersistentClient construction is
cheap relative to the embedding model, so there's no reuse benefit that
would justify a second singleton lifecycle.

query() is implemented and smoke-tested here but has no caller yet -
the Retriever Agent lands in Phase 5.
"""

import uuid
from dataclasses import dataclass
from typing import Protocol

import chromadb

from app.core.config import Settings
from app.database.models import Chunk


def _collection_name(tenant_id: uuid.UUID) -> str:
    return f"hr_policies_{tenant_id}"


@dataclass(frozen=True)
class RetrievedVector:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_name: str
    page_start: int
    page_end: int
    section_title: str | None
    text: str
    distance: float


class VectorStoreService(Protocol):
    def add_chunks(
        self,
        *,
        tenant_id: uuid.UUID,
        document_name: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None: ...

    def delete_by_document(self, *, tenant_id: uuid.UUID, document_id: uuid.UUID) -> int: ...

    def query(
        self, *, tenant_id: uuid.UUID, query_embedding: list[float], top_k: int = 8
    ) -> list[RetrievedVector]: ...

    def reset_collection(self, tenant_id: uuid.UUID) -> None: ...

    def heartbeat(self) -> bool: ...


class ChromaVectorStore:
    def __init__(self, settings: Settings) -> None:
        self._client = chromadb.PersistentClient(path=settings.chroma_dir)

    def _collection(self, tenant_id: uuid.UUID):
        return self._client.get_or_create_collection(
            name=_collection_name(tenant_id), metadata={"hnsw:space": "cosine"}
        )

    def add_chunks(
        self,
        *,
        tenant_id: uuid.UUID,
        document_name: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
    ) -> None:
        if not chunks:
            return
        collection = self._collection(tenant_id)
        collection.add(
            ids=[str(chunk.id) for chunk in chunks],
            embeddings=embeddings,
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {
                    "tenant_id": str(tenant_id),
                    "document_id": str(chunk.document_id),
                    "document_name": document_name,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section_title": chunk.section_title or "",
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunks
            ],
        )

    def delete_by_document(self, *, tenant_id: uuid.UUID, document_id: uuid.UUID) -> int:
        collection = self._collection(tenant_id)
        existing = collection.get(where={"document_id": str(document_id)})
        ids = existing["ids"]
        if ids:
            collection.delete(ids=ids)
        return len(ids)

    def query(
        self, *, tenant_id: uuid.UUID, query_embedding: list[float], top_k: int = 8
    ) -> list[RetrievedVector]:
        collection = self._collection(tenant_id)
        if collection.count() == 0:
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            where={"tenant_id": str(tenant_id)},
        )
        if not results["ids"] or not results["ids"][0]:
            return []

        retrieved: list[RetrievedVector] = []
        for index, chunk_id in enumerate(results["ids"][0]):
            metadata = results["metadatas"][0][index]
            retrieved.append(
                RetrievedVector(
                    chunk_id=uuid.UUID(chunk_id),
                    document_id=uuid.UUID(metadata["document_id"]),
                    document_name=metadata["document_name"],
                    page_start=metadata["page_start"],
                    page_end=metadata["page_end"],
                    section_title=metadata["section_title"] or None,
                    text=results["documents"][0][index],
                    distance=results["distances"][0][index],
                )
            )
        return retrieved

    def reset_collection(self, tenant_id: uuid.UUID) -> None:
        """Drop and recreate a tenant's collection empty (used by the
        index-rebuild script, ADR-005 - Chroma is a rebuildable index)."""
        name = _collection_name(tenant_id)
        try:
            self._client.delete_collection(name=name)
        except Exception:  # noqa: BLE001 - fine if the collection didn't exist yet
            pass
        self._client.get_or_create_collection(name=name, metadata={"hnsw:space": "cosine"})

    def heartbeat(self) -> bool:
        try:
            self._client.heartbeat()
            return True
        except Exception:  # noqa: BLE001 - any failure just means "down"
            return False
