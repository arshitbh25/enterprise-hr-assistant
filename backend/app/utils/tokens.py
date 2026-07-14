"""Token counting (SDD Section 9: app/utils/).

Phase 4: real BAAI/bge-small-en-v1.5 token counts, replacing the Phase 3
word-based approximation - same public signature, so the chunker is
unaffected by the swap. Uses a lightweight, independently-cached
tokenizer-only load (transformers.AutoTokenizer) rather than the full
Embedder: counting tokens only needs the vocabulary/merges files, not
the loaded model, and keeping this decoupled from app.embeddings means
the chunker's unit tests don't have to pull in a full SentenceTransformer
load just to size chunks.
"""

from functools import lru_cache

from transformers import AutoTokenizer

from app.core.config import get_settings


@lru_cache
def _tokenizer():
    return AutoTokenizer.from_pretrained(get_settings().embedding_model_hf_id)


def approx_token_count(text: str) -> int:
    return len(_tokenizer().encode(text, add_special_tokens=False))
