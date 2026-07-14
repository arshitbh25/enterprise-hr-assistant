"""Unit tests for app/embeddings/registry.py.

Verifies the process-wide singleton lifecycle (mirrors
app.database.session's init_engine()/get_engine()): get_embedder() is a
lazy singleton, and re-initializing with the same model name is a
no-op that returns the already-loaded instance rather than reloading.
"""

import pytest

from app.core.config import Settings
from app.embeddings import registry

pytestmark = pytest.mark.model


@pytest.fixture(autouse=True)
def _reset_registry_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(registry, "_embedder", None)
    monkeypatch.setattr(registry, "_embedder_model_name", None)
    yield
    monkeypatch.setattr(registry, "_embedder", None)
    monkeypatch.setattr(registry, "_embedder_model_name", None)


def test_get_embedder_lazily_initializes_and_is_a_singleton():
    first = registry.get_embedder()
    second = registry.get_embedder()
    assert first is second


def test_init_embedder_is_idempotent_for_the_same_model_name():
    settings = Settings(_env_file=None)
    first = registry.init_embedder(settings)
    second = registry.init_embedder(settings)
    assert first is second
