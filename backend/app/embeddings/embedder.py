"""BGE embedding adapter (SDD Section 7.2 Stage 5, Appendix A, ADR-002).

Runs BAAI/bge-small-en-v1.5 locally via sentence-transformers: 384-dim,
L2-normalized vectors (so cosine similarity reduces to a dot product).
Passages are embedded raw; queries get BGE's recommended retrieval
instruction prefix, which is why embed_query and embed_passages are two
distinct methods rather than one with a flag - callers can't accidentally
mix them up.
"""

from sentence_transformers import SentenceTransformer

_QUERY_INSTRUCTION_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder:
    def __init__(self, model_name: str, batch_size: int) -> None:
        self.model_name = model_name
        self._batch_size = batch_size
        self._model = SentenceTransformer(model_name)

    @property
    def dimension(self) -> int:
        return self._model.get_embedding_dimension()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        vector = self._model.encode(
            _QUERY_INSTRUCTION_PREFIX + text,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vector.tolist()
