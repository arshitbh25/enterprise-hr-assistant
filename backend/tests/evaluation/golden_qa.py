"""Golden Q&A cases for the Phase 5 evaluation set (SDD Section 13 P5 exit
criteria: "Golden set v0 (20 Q&A): 100% citation presence, 0 fabricated
answers on adversarial 'not in doc' questions").

Single source of truth, imported by both
tests/evaluation/test_golden_set.py (the pytest assertions) and
scripts/calibrate_threshold.py (reproducible threshold re-calibration
whenever the fixture document or the embedding model changes).

All cases run against tests/evaluation/fixtures/sample_hr_policy.pdf, a
committed fixture covering five real policy topics: Leave Policy, Dress
Code, Travel and Reimbursement, Notice Period, and Code of Conduct.

Adversarial cases are split into two tiers (see docs/threshold-calibration.md
for the measurements behind this split):

- OFF_TOPIC: genuinely unrelated content. Real cosine similarity against
  every chunk in the fixture measures well below
  retrieval_similarity_threshold (0.50) - these are rejected by the real
  threshold gate before the LLM is ever called. No monkeypatching.
- TOPICALLY_ADJACENT: a real aspect of one of the five covered topics
  that the fixture does NOT actually address (e.g. maternity leave vs.
  the fixture's casual/earned leave). These score well ABOVE the
  threshold (0.61-0.72 measured) because they're genuinely similar in
  topic and vocabulary - they legitimately reach the LLM, and rejecting
  them correctly depends on the model's own NOT_FOUND compliance, not
  retrieval. The offline fake-LLM run cannot prove real model
  compliance here; it only proves the citation/refusal-normalization
  plumbing is wired correctly. These are the priority cases for the
  documented live Gemini run.

MULTI_TURN_CASES (added for the P6 exit criterion "multi-turn eval
passes") exercise the Memory + Query Understanding + Retriever chain
across two real turns of the same session - see MultiTurnCase's own
docstring for what's faked (only the rewrite's own text) versus what
runs for real (everything downstream of it).
"""

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class AnswerableCase:
    question: str
    expected_section: str


@dataclass(frozen=True)
class MultiTurnCase:
    """A two-turn conversation: a first question, then a follow-up that
    only makes sense with the first turn's context ("...and for
    interns?"). `rewritten_follow_up` is what Query Understanding's
    rewrite call is faked to produce for this specific follow-up
    (test_golden_set.py has no real Gemini to do the rewriting itself) -
    everything downstream of that rewrite (retrieval, ranking, prompt
    construction, citation) runs for real against the real fixture,
    which is the thing this case actually proves (SDD §13 P6 exit
    criterion: "multi-turn eval passes")."""

    first_question: str
    follow_up_question: str
    rewritten_follow_up: str
    expected_section: str


class AdversarialTier(str, Enum):
    OFF_TOPIC = "off_topic"
    TOPICALLY_ADJACENT = "topically_adjacent"


@dataclass(frozen=True)
class AdversarialCase:
    question: str
    tier: AdversarialTier


ANSWERABLE_CASES: list[AnswerableCase] = [
    AnswerableCase("How many casual leave days do I get per year?", "Leave Policy"),
    AnswerableCase("Can I carry forward my earned leave?", "Leave Policy"),
    AnswerableCase("What is the dress code on Fridays?", "Dress Code"),
    AnswerableCase("Is formal attire required for client meetings?", "Dress Code"),
    AnswerableCase(
        "How many days do I have to submit a travel reimbursement claim?",
        "Travel and Reimbursement",
    ),
    AnswerableCase(
        "Are alcohol expenses reimbursable during business travel?", "Travel and Reimbursement"
    ),
    AnswerableCase("How long is the notice period for a manager who resigns?", "Notice Period"),
    AnswerableCase("What happens if I don't serve my full notice period?", "Notice Period"),
    AnswerableCase("Who should I report workplace harassment to?", "Code of Conduct"),
    AnswerableCase(
        "Does the company have a zero-tolerance policy on harassment?", "Code of Conduct"
    ),
]

ADVERSARIAL_CASES: list[AdversarialCase] = [
    # Tier: OFF_TOPIC - measured max 0.44 against the fixture, comfortably
    # below the 0.50 threshold. Must produce NOT_FOUND via real retrieval
    # scores alone; the LLM is never called.
    AdversarialCase("What is the capital of France?", AdversarialTier.OFF_TOPIC),
    AdversarialCase("Who won the FIFA World Cup in 2018?", AdversarialTier.OFF_TOPIC),
    AdversarialCase(
        "What is the boiling point of water in Celsius?", AdversarialTier.OFF_TOPIC
    ),
    AdversarialCase("Please write a Python function to sort a list.", AdversarialTier.OFF_TOPIC),
    AdversarialCase(
        "What is the process for a performance improvement plan?", AdversarialTier.OFF_TOPIC
    ),
    # Tier: TOPICALLY_ADJACENT - measured 0.61-0.72 against the fixture,
    # above threshold, so these reach the LLM. Genuinely absent from the
    # fixture's actual content despite the topical overlap.
    AdversarialCase("What is the maternity leave duration?", AdversarialTier.TOPICALLY_ADJACENT),
    AdversarialCase("What is the sick leave policy?", AdversarialTier.TOPICALLY_ADJACENT),
    AdversarialCase(
        "What is the dress code for remote/work-from-home days?",
        AdversarialTier.TOPICALLY_ADJACENT,
    ),
    AdversarialCase(
        "Can I get reimbursed for a professional certification course?",
        AdversarialTier.TOPICALLY_ADJACENT,
    ),
    AdversarialCase(
        "What is the notice period during the probation period?",
        AdversarialTier.TOPICALLY_ADJACENT,
    ),
]

MULTI_TURN_CASES: list[MultiTurnCase] = [
    MultiTurnCase(
        first_question="How many casual leave days do I get per year?",
        follow_up_question="What about earned leave?",
        rewritten_follow_up="How many earned leave days do I get per year?",
        expected_section="Leave Policy",
    ),
    MultiTurnCase(
        first_question="What is the dress code on Fridays?",
        follow_up_question="And for client meetings?",
        rewritten_follow_up="Is formal attire required for client meetings?",
        expected_section="Dress Code",
    ),
    MultiTurnCase(
        first_question="How long is the notice period for a manager who resigns?",
        follow_up_question="What about for a regular employee?",
        rewritten_follow_up="How long is the notice period for a regular employee who resigns?",
        expected_section="Notice Period",
    ),
]
