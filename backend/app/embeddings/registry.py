"""Embedding model registry (SDD Section 9: embeddings/registry.py).

Maps the short EMBEDDING_MODEL_NAME label (stored on every chunk row,
app.core.constants) to an Embedder factory - a second model later is a
new dict entry, not a redesign. Process-wide singleton lifecycle
deliberately mirrors app.database.session's init_engine()/get_engine():
init_embedder() is called once from the app lifespan so the model loads
at startup and never per-request; get_embedder() is how background
tasks (which have no request to read app.state from) reach the same
instance, the same way they already reach the DB via
get_session_factory().

Unlike init_engine() (which always rebuilds - each test wants a fresh
DB), init_embedder() is idempotent: reloading a multi-hundred-MB model
has no per-test benefit, only cost, so re-init with the same model name
is a no-op that returns the already-loaded instance.
"""

from collections.abc import Callable

from app.core.config import Settings, get_settings
from app.core.constants import EMBEDDING_MODEL_NAME
from app.embeddings.embedder import Embedder

_ADAPTERS: dict[str, Callable[[Settings], Embedder]] = {
    EMBEDDING_MODEL_NAME: lambda settings: Embedder(
        model_name=settings.embedding_model_hf_id,
        batch_size=settings.embedding_batch_size,
    ),
}

_embedder: Embedder | None = None
_embedder_model_name: str | None = None


def init_embedder(
    settings: Settings | None = None, *, model_name: str = EMBEDDING_MODEL_NAME
) -> Embedder:
    global _embedder, _embedder_model_name
    if _embedder is not None and _embedder_model_name == model_name:
        return _embedder

    settings = settings or get_settings()
    factory = _ADAPTERS[model_name]
    _embedder = factory(settings)
    _embedder_model_name = model_name
    return _embedder


def get_embedder() -> Embedder:
    if _embedder is None:
        init_embedder()
    assert _embedder is not None
    return _embedder
