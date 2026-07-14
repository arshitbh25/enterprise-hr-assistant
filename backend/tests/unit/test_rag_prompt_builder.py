"""Unit tests for app/rag/prompt_builder.py (SDD Section 6.3.5, 7.2 Stage 9)."""

import uuid

import pytest

from app.core.config import Settings
from app.core.constants import NOT_FOUND_TOKEN
from app.rag import prompt_builder
from app.rag.prompt_builder import build_prompt, get_answer_template, init_prompt_templates
from app.rag.ranking import RankedBlock

pytestmark = pytest.mark.model


def _block(**overrides) -> RankedBlock:
    defaults = dict(
        document_id=uuid.uuid4(),
        document_name="Leave_Policy.pdf",
        page_start=12,
        page_end=12,
        section_title="Casual Leave",
        text="Employees receive twelve days of casual leave per year.",
        score=0.9,
        token_count=10,
        source_chunk_ids=[uuid.uuid4()],
    )
    defaults.update(overrides)
    return RankedBlock(**defaults)


def _settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


@pytest.fixture(autouse=True)
def _reset_template_cache():
    init_prompt_templates()
    yield
    init_prompt_templates()


def test_init_prompt_templates_loads_the_real_template():
    init_prompt_templates()
    template = get_answer_template()
    assert "$sources" in template.template
    assert "$question" in template.template


def test_init_prompt_templates_raises_when_file_missing(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(prompt_builder, "_PROMPTS_DIR", tmp_path)

    with pytest.raises(FileNotFoundError):
        init_prompt_templates()


def test_build_prompt_wraps_single_page_source_correctly():
    block = _block(page_start=12, page_end=12, document_name="Leave_Policy.pdf")

    built = build_prompt("How many casual leaves?", [block], settings=_settings())

    assert '<source id="S1" doc="Leave_Policy.pdf" page="12">' in built.text
    assert block.text in built.text
    assert "</source>" in built.text


def test_build_prompt_uses_page_range_when_start_differs_from_end():
    block = _block(page_start=12, page_end=14)

    built = build_prompt("question", [block], settings=_settings())

    assert 'page="12-14"' in built.text


def test_build_prompt_includes_question_delimited_last():
    built = build_prompt("How many casual leaves do I get?", [_block()], settings=_settings())

    assert built.text.rstrip().endswith("</question>")
    assert "<question>\nHow many casual leaves do I get?\n</question>" in built.text


def test_build_prompt_includes_not_found_token_instruction():
    built = build_prompt("question", [_block()], settings=_settings())

    assert NOT_FOUND_TOKEN in built.text


def test_build_prompt_numbers_multiple_sources_in_order():
    first = _block(document_name="A.pdf", score=0.9)
    second = _block(document_name="B.pdf", score=0.8)

    built = build_prompt("question", [first, second], settings=_settings())

    assert built.text.index('id="S1" doc="A.pdf"') < built.text.index('id="S2" doc="B.pdf"')


def test_build_prompt_drops_lowest_scored_block_when_over_budget():
    long_text = "word " * 100
    high = _block(score=0.9, text=long_text, document_name="High.pdf")
    low = _block(score=0.5, text=long_text, document_name="Low.pdf")

    built = build_prompt("question", [high, low], settings=_settings(prompt_token_budget=50))

    assert len(built.blocks) == 1
    assert built.blocks[0].document_name == "High.pdf"
    assert "Low.pdf" not in built.text


def test_build_prompt_always_keeps_at_least_one_block_even_if_oversized():
    oversized = _block(score=0.9, text="word " * 500)

    built = build_prompt("question", [oversized], settings=_settings(prompt_token_budget=1))

    assert len(built.blocks) == 1


def test_build_prompt_wraps_history_in_a_delimited_tag():
    built = build_prompt(
        "question", [_block()], history="Q: Prior question?\nA: Prior answer.", settings=_settings()
    )

    assert "<history>\nQ: Prior question?\nA: Prior answer.\n</history>" in built.text


def test_build_prompt_omits_history_tag_when_history_is_empty():
    built = build_prompt("question", [_block()], settings=_settings())

    assert "</history>" not in built.text


def test_build_prompt_drops_history_before_giving_up_when_still_over_budget():
    block = _block(score=0.9, text="short source text")
    long_history = "word " * 100

    built = build_prompt(
        "question", [block], history=long_history, settings=_settings(prompt_token_budget=50)
    )

    assert len(built.blocks) == 1  # the single block is never dropped for history's sake
    assert "</history>" not in built.text
