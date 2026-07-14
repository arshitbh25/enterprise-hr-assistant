"""Unit tests for app/utils/tokens.py (Phase 4: real BGE tokenizer counts)."""

import pytest

from app.utils.tokens import approx_token_count

pytestmark = pytest.mark.model


def test_returns_positive_int_for_real_text():
    count = approx_token_count("Employees receive twelve days of annual leave per year.")
    assert isinstance(count, int)
    assert count > 0


def test_scales_roughly_with_text_length():
    short_count = approx_token_count("Leave policy.")
    long_count = approx_token_count("Leave policy. " * 20)
    assert long_count > short_count


def test_empty_string_is_zero():
    assert approx_token_count("") == 0
