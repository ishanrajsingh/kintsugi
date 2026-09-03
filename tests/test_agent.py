"""Tests for the agent: taxonomy, detector, policy behaviour, and evaluation.

The most important tests here are the ones asserting what the agent must
*never* do. A recovery agent that occasionally hammers a closed account or
messages a customer six times is not a slightly worse agent; it is one that
cannot be deployed.
"""

from __future__ import annotations

import numpy as np
import pytest

from kintsugi.agent.health_monitor import (
    InferredState, IssuerHealthMonitor, score_detection,
)
from kintsugi.agent.kintsugi import AgentConfig, KintsugiPolicy
from kintsugi.agent.messaging import MessageWriter, validate
from kintsugi.agent.policy import FixedRetryPolicy, RuleBasedPolicy
from kintsugi.domain import (
    Action, ActionKind, Attempt, Channel, FailureClass, Payment, Rail,
)
from kintsugi.eval import metrics as M
from kintsugi.eval.harness import compare, evaluate, verify_crn
from kintsugi.taxonomy import rules
from kintsugi.taxonomy.classifier import TaxonomyResolver, _parse_label
from kintsugi.world.simulator import World, WorldConfig

SMALL = WorldConfig(n_customers=400, n_payments=1200, seed=42)


class _StubModel:
    """Constant-probability stand-in, so policy logic can be tested alone."""

    def __init__(self, p: float = 0.3) -> None:
        self.p = p

    def predict(self, x) -> float:
        return self.p

    def predict_batch(self, X) -> np.ndarray:
        return np.full(len(X), self.p)


def _payment(cause: FailureClass, amount: int = 100_000, **kw) -> Payment:
    p = Payment(
        payment_id="pay_test", customer_id="cust_0", merchant_id="m",
        amount_paise=amount, preferred_rail=kw.pop("rail", Rail.UPI_INTENT),
        issuer="MRDN", created_at=0, is_recurring=kw.pop("is_recurring", False),
    )
    p.attempts.append(Attempt(
        attempt_no=0, at=0, rail=p.preferred_rail, succeeded=False,
        failure_class=cause, raw_error="synthetic"))
    return p


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("51 - Insufficient funds", FailureClass.INSUFFICIENT_FUNDS),
    ("Z9: Insufficient balance in remitter account", FailureClass.INSUFFICIENT_FUNDS),
    ("91 - Issuer or switch inoperative", FailureClass.ISSUER_DOWN),
    ("U30: Debit failed at remitter bank", FailureClass.ISSUER_DOWN),
    ("05 - Do not honor", FailureClass.RISK_DECLINE),
    ("54 - Expired card", FailureClass.INVALID_INSTRUMENT),
    ("U69: Collect request expired", FailureClass.AUTH_TIMEOUT),
    ("ZM: Invalid or missing MPIN", FailureClass.AUTH_ABANDONED),
    ("Transaction cancelled by user", FailureClass.USER_CANCELLED),
    ("Mandate has been revoked by the payer", FailureClass.MANDATE_REVOKED),
])
def test_rules_classify_known_codes(text, expected):
    assert rules.classify(text)[0] is expected


def test_otp_expiry_is_not_an_expired_card():
    """Both say 'expired'; rule order must resolve it. Regression guard."""
    assert rules.classify("OTP expired before submission")[0] is FailureClass.AUTH_TIMEOUT
    assert rules.classify("54 - Expired card")[0] is FailureClass.INVALID_INSTRUMENT


def test_rules_are_perfect_on_visible_and_blind_on_holdout():
    """The measurement that justifies having a model at all."""
    cov = rules.coverage()
    assert cov["visible"]["accuracy"] == 1.0
    assert cov["holdout"]["accuracy"] < 0.2
    # Whatever the rules cannot match must come back UNKNOWN, never a
    # confident wrong class -- the policy handles UNKNOWN conservatively.
    assert cov["holdout"]["unmatched"] == cov["holdout"]["n"]


def test_unmatched_strings_return_unknown():
    assert rules.classify("something nobody has ever written")[0] is FailureClass.UNKNOWN
    assert rules.classify(None)[0] is FailureClass.UNKNOWN
    assert rules.classify("")[0] is FailureClass.UNKNOWN


def test_resolver_works_with_no_model_available():
    """Graceful degradation is a requirement, not a nicety."""
    resolver = TaxonomyResolver(use_llm=False)
    assert resolver.classify("51 - Insufficient funds").failure_class is (
        FailureClass.INSUFFICIENT_FUNDS)
    assert resolver.classify("brand new string").failure_class is FailureClass.UNKNOWN


def test_model_output_is_validated_against_the_enum():
    assert _parse_label("INSUFFICIENT_FUNDS") == "INSUFFICIENT_FUNDS"
    assert _parse_label("The answer is ISSUER_DOWN.") == "ISSUER_DOWN"
    assert _parse_label("BANANA_CLASS") is None
    assert _parse_label("") is None
    assert _parse_label(None) is None


# ---------------------------------------------------------------------------
# Health monitor
# ---------------------------------------------------------------------------


def test_monitor_ignores_non_technical_failures():
    """Balance failures must not look like an outage, however many there are."""
    monitor = IssuerHealthMonitor()
    for i in range(400):
        monitor.observe("MRDN", i * 10, False, FailureClass.INSUFFICIENT_FUNDS)
    assert monitor.state("MRDN") is InferredState.HEALTHY


def test_monitor_detects_a_burst_of_technical_declines():
    monitor = IssuerHealthMonitor()
    for i in range(300):
        monitor.observe("MRDN", i, True, None)
    assert monitor.state("MRDN") is InferredState.HEALTHY
    for i in range(40):
        monitor.observe("MRDN", 300 + i, False, FailureClass.ISSUER_DOWN)
    assert monitor.state("MRDN").is_impaired


def test_monitor_recovers_after_the_incident_ends():
    monitor = IssuerHealthMonitor()
    for i in range(300):
        monitor.observe("MRDN", i, True, None)
    for i in range(40):
        monitor.observe("MRDN", 300 + i, False, FailureClass.ISSUER_DOWN)
    assert monitor.state("MRDN").is_impaired
    for i in range(300):
        monitor.observe("MRDN", 400 + i, True, None)
    assert monitor.state("MRDN") is InferredState.HEALTHY


def test_monitor_keeps_issuers_independent():
    monitor = IssuerHealthMonitor()
    for i in range(300):
        monitor.observe("MRDN", i, True, None)
        monitor.observe("ASTR", i, True, None)
    for i in range(40):
        monitor.observe("MRDN", 300 + i, False, FailureClass.ISSUER_DOWN)
    assert monitor.state("MRDN").is_impaired
    assert monitor.state("ASTR") is InferredState.HEALTHY


# ---------------------------------------------------------------------------
# Policy behaviour -- the things that must never happen
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cause", [
    FailureClass.ACCOUNT_CLOSED,
    FailureClass.CARD_BLOCKED,
    FailureClass.INVALID_INSTRUMENT,
    FailureClass.MANDATE_REVOKED,
])
def test_agent_never_retries_a_dead_instrument(cause):
    agent = KintsugiPolicy(retry_model=_StubModel(0.99),
                           nudge_model=_StubModel(0.99))
    action = agent.decide(_payment(cause, amount=10_000_000), 100, None)
    assert action.kind is ActionKind.ABANDON, (
        "a high predicted probability must not override a terminal cause")


def test_rule_based_also_stops_on_terminal_causes():
    action = RuleBasedPolicy().decide(
        _payment(FailureClass.ACCOUNT_CLOSED), 100, None)
    assert action.kind is ActionKind.ABANDON


def test_agent_stops_when_nothing_is_worth_its_cost():
    agent = KintsugiPolicy(retry_model=_StubModel(0.0),
                           nudge_model=_StubModel(0.0))
    action = agent.decide(_payment(FailureClass.RISK_DECLINE, amount=500),
                          100, None)
    assert action.kind is ActionKind.ABANDON


def test_agent_respects_the_contact_budget():
    agent = KintsugiPolicy(retry_model=_StubModel(0.01),
                           nudge_model=_StubModel(0.9),
                           config=AgentConfig(max_nudges=2))
    payment = _payment(FailureClass.AUTH_ABANDONED, amount=5_000_000)
    from kintsugi.domain import Nudge
    for i in range(2):
        payment.nudges.append(Nudge(at=i * 100, channel=Channel.SMS,
                                    template_id="t", cost_paise=20))
    action = agent.decide(payment, 300, None)
    assert action.kind is not ActionKind.NUDGE


def test_agent_prices_actions_in_rupees():
    agent = KintsugiPolicy(retry_model=_StubModel(0.5),
                           nudge_model=_StubModel(0.01))
    action = agent.decide(_payment(FailureClass.RISK_DECLINE, amount=200_000),
                          100, None)
    assert action.expected_value_paise > 0
    assert action.rationale


def test_agent_explains_every_decision():
    agent = KintsugiPolicy(retry_model=_StubModel(0.4),
                           nudge_model=_StubModel(0.2))
    for cause in (FailureClass.INSUFFICIENT_FUNDS, FailureClass.ISSUER_DOWN,
                  FailureClass.AUTH_ABANDONED, FailureClass.ACCOUNT_CLOSED):
        action = agent.decide(_payment(cause), 500, None)
        assert action.rationale, f"{cause.name} produced an unexplained action"


def test_agent_does_not_switch_rails_for_a_balance_failure():
    """A different door into the same empty account is still empty."""
    agent = KintsugiPolicy(retry_model=_StubModel(0.5),
                           nudge_model=_StubModel(0.01))
    payment = _payment(FailureClass.INSUFFICIENT_FUNDS)
    assert agent._candidate_rails(payment) == [payment.preferred_rail]

    payment = _payment(FailureClass.ISSUER_DOWN)
    assert len(agent._candidate_rails(payment)) == 2


# ---------------------------------------------------------------------------
# Messaging guardrails
# ---------------------------------------------------------------------------


def test_message_validation_rejects_invented_promises():
    assert validate("Your payment failed. Get a full refund now, no penalty.",
                    Channel.SMS, False) is not None
    assert validate("Payment failed. Call us at 1800 123 4567.",
                    Channel.SMS, False) is not None


def test_message_validation_enforces_sms_length():
    assert validate("x" * 200, Channel.SMS, False) is not None
    assert validate("Your payment did not go through. Please add funds and we "
                    "will retry it shortly.", Channel.SMS, False) is None


def test_message_validation_requires_a_link_when_needed():
    assert validate("Your payment is waiting for approval, please complete it.",
                    Channel.SMS, True) is not None


def test_templates_exist_and_are_safe_for_every_cause():
    writer = MessageWriter(use_llm=False)
    for cause in FailureClass:
        for channel in Channel:
            message = writer.write(cause, channel, 125_000)
            assert message.text
            assert "{" not in message.text, "unfilled placeholder shipped"
            assert len(message.text) <= 500


def test_amounts_use_indian_digit_grouping():
    from kintsugi.agent.messaging import _format_inr
    assert _format_inr(12_345_600) == "INR 1,23,456"


# ---------------------------------------------------------------------------
# Evaluation machinery
# ---------------------------------------------------------------------------


def test_harness_verifies_crn_before_reporting():
    policies = [FixedRetryPolicy(), RuleBasedPolicy()]
    check = verify_crn(1000, policies, SMALL)
    assert check["crn_intact"]
    assert check["mismatches"] == 0


def test_paired_comparison_reports_an_interval():
    results = evaluate([FixedRetryPolicy(), RuleBasedPolicy()], SMALL,
                       n_seeds=6, progress=False)
    c = compare(results, "fixed_retry", "rule_based", "recovery_rate")
    assert c.ci_low <= c.mean_diff <= c.ci_high
    assert 0.0 <= c.win_rate <= 1.0
    assert 0.0 <= c.p_value <= 1.0


def test_metrics_denominator_is_recoverable_payments():
    world = World(SMALL)
    metrics = M.compute(world.run(RuleBasedPolicy()))
    assert metrics.failed_first_attempt > 0
    assert metrics.recovered <= metrics.failed_first_attempt
    assert 0.0 <= metrics.recovery_rate <= 1.0


def test_wasted_retries_counts_attempts_after_a_terminal_failure():
    world = World(SMALL)
    aggressive = M.compute(world.run(FixedRetryPolicy(
        retry_offsets=(30, 60, 120, 240), nudge_offsets=())))
    careful = M.compute(world.run(RuleBasedPolicy()))
    assert aggressive.wasted_retries > 0
    assert careful.wasted_retries == 0
