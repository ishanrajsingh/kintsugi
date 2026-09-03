"""Tests for the merchant-facing explanation surface.

The property under test is not "does it answer well" but "can it answer with a
number that is not true". Everything else about this component is cosmetic; that
one thing is what decides whether it can be shown to someone whose money is
involved.
"""

from __future__ import annotations

import pytest

import numpy as np

from kintsugi.agent.explain import (
    DecisionExplainer, LedgerIndex, verify_grounded,
)
from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.world.simulator import World, WorldConfig

SMALL = WorldConfig(n_customers=400, n_payments=1200, seed=1000)


class _StubModel:
    """Fixed probability, so the suite needs no trained artefacts.

    Tests must pass on a fresh clone, before anyone has run the training
    script. Depending on a pickled model here would make `pytest` fail for a
    reviewer who has only just cloned the repository -- and would also couple
    these tests to whatever the model happens to predict this week, which is
    not what they are checking.
    """

    def __init__(self, p: float = 0.35) -> None:
        self.p = p

    def predict(self, x) -> float:
        return self.p

    def predict_batch(self, X) -> np.ndarray:
        return np.full(len(X), self.p)


@pytest.fixture(scope="module")
def explainer() -> DecisionExplainer:
    world = World(SMALL)
    agent = KintsugiPolicy(retry_model=_StubModel(0.4),
                           nudge_model=_StubModel(0.2))
    result = world.run(agent)
    index = LedgerIndex.build(agent.decisions, result.payments)
    return DecisionExplainer(index, use_llm=False)


# ---------------------------------------------------------------------------
# Grounding -- the check that makes this safe to show anyone
# ---------------------------------------------------------------------------


def test_invented_figures_are_rejected():
    facts = ["Payment pay_000123 is for INR 4,500.", "It was recovered on day 3."]
    assert verify_grounded("We recovered the INR 4,500 payment on day 3.",
                           facts) is None
    assert verify_grounded("We recovered INR 91,200 after 7 retries.",
                           facts) is not None


def test_rounding_of_a_supplied_figure_is_tolerated():
    facts = ["The agent recovered INR 1,234,567 in total."]
    assert verify_grounded("It recovered about INR 1,234,000.", facts) is None


def test_percentages_are_allowed_without_being_stated():
    facts = ["228 of 299 payments were recovered."]
    assert verify_grounded("That is roughly 76% of them.", facts) is None


def test_prose_without_numbers_always_passes():
    facts = ["Payment pay_1 failed with ACCOUNT_CLOSED."]
    assert verify_grounded(
        "The account is closed, so no retry could have worked.", facts) is None


def test_unsupported_figure_is_named_in_the_rejection():
    facts = ["Payment pay_1 is for INR 500."]
    problem = verify_grounded("We spent INR 88,888 chasing it.", facts)
    assert problem is not None and "88,888" in problem


# ---------------------------------------------------------------------------
# Retrieval is deterministic and grounded in the ledger
# ---------------------------------------------------------------------------


def test_named_payment_returns_its_own_history(explainer):
    pid = next(iter(explainer.index.payments))
    facts, n = explainer.gather_facts(f"why did you not chase {pid}?")
    assert n > 0
    assert any(pid in f for f in facts)


def test_unknown_payment_says_so_rather_than_inventing(explainer):
    facts, _ = explainer.gather_facts("what happened to pay_999999?")
    assert any("No payment pay_999999 exists" in f for f in facts)


def test_cause_questions_summarise_that_cause(explainer):
    facts, _ = explainer.gather_facts(
        "what did you do about insufficient funds failures?")
    assert any("INSUFFICIENT_FUNDS" in f for f in facts)


def test_terminal_causes_explain_why_nothing_was_tried(explainer):
    facts, _ = explainer.gather_facts("why did you give up on account closed?")
    assert any("terminal" in f.lower() for f in facts)


def test_contact_questions_report_the_contact_budget(explainer):
    facts, _ = explainer.gather_facts("why so many messages to customers?")
    assert any("messages were sent" in f or "No customers were messaged" in f
               for f in facts)


def test_any_question_produces_some_grounded_facts(explainer):
    for question in ("how much did we recover?",
                     "why are you waiting so long?",
                     "what is going on?",
                     ""):
        facts, _ = explainer.gather_facts(question)
        assert facts, f"no facts for {question!r}"


def test_answer_falls_back_to_facts_with_no_model(explainer):
    answer = explainer.answer("how much did we recover overall?")
    assert answer.source == "deterministic"
    assert answer.facts
    assert answer.text


def test_every_generated_fact_is_self_consistent(explainer):
    """Facts must survive their own grounding check.

    If the deterministic summary could not pass `verify_grounded` against its
    own fact list, the check would be rejecting truthful answers and the
    fallback would be the only path ever taken.
    """
    facts, _ = explainer.gather_facts("how much did we recover overall?")
    joined = " ".join(facts)
    assert verify_grounded(joined, facts) is None
