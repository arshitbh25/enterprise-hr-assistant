"""Unit tests for app/embeddings/embedder.py (SDD Section 7.2 Stage 5).

Loads the real BAAI/bge-small-en-v1.5 model once per test session
(module-scoped fixture) - the point of these tests is to verify the
actual model's behavior (dimension, normalization, query-prefix effect),
not a mock of it.
"""

import numpy as np
import pytest

from app.embeddings.embedder import Embedder

pytestmark = pytest.mark.model


@pytest.fixture(scope="module")
def embedder() -> Embedder:
    return Embedder(model_name="BAAI/bge-small-en-v1.5", batch_size=32)


def test_dimension_is_384(embedder: Embedder):
    assert embedder.dimension == 384
    [vector] = embedder.embed_passages(["Employees receive twelve days of annual leave."])
    assert len(vector) == 384


def test_embeddings_are_l2_normalized(embedder: Embedder):
    [vector] = embedder.embed_passages(["Employees receive twelve days of annual leave."])
    assert np.linalg.norm(vector) == pytest.approx(1.0, abs=1e-4)

    query_vector = embedder.embed_query("how many casual leaves do I get")
    assert np.linalg.norm(query_vector) == pytest.approx(1.0, abs=1e-4)


def test_query_prefix_is_applied_only_to_queries(embedder: Embedder):
    text = "how many casual leaves do I get"
    query_vector = embedder.embed_query(text)
    [passage_vector] = embedder.embed_passages([text])

    assert query_vector != passage_vector


def test_leave_passage_scores_higher_than_dress_code_passage(embedder: Embedder):
    query = "how many casual leaves do I get"
    passage_leave = (
        "Employees are entitled to twelve days of casual leave per calendar year. "
        "Casual leave can be availed for personal reasons with prior manager approval."
    )
    passage_dress_code = (
        "Employees are expected to dress in business casual attire during office hours. "
        "Formal attire is required for client-facing meetings."
    )

    query_vector = np.array(embedder.embed_query(query))
    leave_vector, dress_vector = (
        np.array(vector) for vector in embedder.embed_passages([passage_leave, passage_dress_code])
    )

    sim_leave = float(np.dot(query_vector, leave_vector))
    sim_dress = float(np.dot(query_vector, dress_vector))

    assert sim_leave > sim_dress


def test_embed_passages_empty_list_returns_empty_list(embedder: Embedder):
    assert embedder.embed_passages([]) == []
