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
    InferredState, IssuerHealthMonitor,
)
from kintsugi.agent.kintsugi import AgentConfig, KintsugiPolicy
from kintsugi.agent.messaging import MessageWriter, validate
from kintsugi.agent.policy import FixedRetryPolicy, RuleBasedPolicy
from kintsugi.domain import (
    ActionKind, Attempt, Channel, FailureClass, Payment, Rail,
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
    assert cov["holdout"]["accuracy"] < 0.3


def test_rules_never_answer_confidently_wrong():
    """The safety property, and the one that is easy to lose.

    An unmatched string is harmless: it becomes UNKNOWN and the policy treats
    it conservatively. A *confidently wrong* class is not, because the policy
    acts on it. This caught a real regression: adding Razorpay's published
    reason identifiers let the `payment_declined` pattern swallow
    `payment_declined_due_to_high_traffic`, which is a different cause
    entirely. Identifier patterns are now anchored so they match a whole
    identifier rather than a prefix.
    """
    cov = rules.coverage()
    confidently_wrong = [m for m in cov["misses"]
                         if m["predicted"] != "UNKNOWN"]
    assert not confidently_wrong, (
        f"rules guessed wrong on {len(confidently_wrong)}: "
        f"{[(m['text'], m['predicted'], m['truth']) for m in confidently_wrong[:3]]}")


def test_the_catalogue_carries_real_razorpay_reasons():
    """The vocabulary should be production, not invention."""
    from kintsugi.taxonomy.codes import RAZORPAY_REASONS, all_strings

    texts = {t for t, _, _ in all_strings()}
    for reason, _fc, _source, _holdout in RAZORPAY_REASONS:
        assert reason in texts, f"{reason} missing from the catalogue"
    # A few identifiers verified directly against Razorpay's published list.
    for reason in ("insufficient_funds", "payment_timed_out",
                   "debit_instrument_blocked", "bank_not_available",
                   "payment_risk_check_failed"):
        assert reason in texts


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
    """The invariant is 'never retry', not 'never act'.

    A dead instrument cannot be charged, and no probability estimate may
    override that. But documented practice on a hard decline is to stop
    retrying and *ask the customer for new details* -- the instrument is dead,
    the customer is not. So contact stays in the action set and only retries
    are removed.
    """
    agent = KintsugiPolicy(retry_model=_StubModel(0.99),
                           nudge_model=_StubModel(0.99))
    action = agent.decide(_payment(cause, amount=10_000_000), 10 * 60, None)
    assert action.kind is not ActionKind.RETRY, (
        "a high predicted probability must not override a terminal cause")


def test_rule_based_also_stops_retrying_terminal_causes():
    action = RuleBasedPolicy().decide(
        _payment(FailureClass.ACCOUNT_CLOSED), 10 * 60, None)
    assert action.kind is not ActionKind.RETRY


@pytest.mark.parametrize("cause", [
    FailureClass.CARD_BLOCKED, FailureClass.INVALID_INSTRUMENT,
])
def test_a_dead_instrument_earns_a_credential_request(cause):
    """Never retrying is correct; writing the payment off is not.

    Account-updater services alone recover 3-5% of recurring revenue, and the
    documented response to a hard decline is a dunning message carrying a
    card-update link. A policy that abandons instead never sends it.
    """
    for policy in (RuleBasedPolicy(),
                   KintsugiPolicy(retry_model=_StubModel(0.0),
                                  nudge_model=_StubModel(0.6))):
        action = policy.decide(_payment(cause, amount=2_000_000), 11 * 60, None)
        assert action.kind is ActionKind.NUDGE, (
            f"{policy.name} wrote off a {cause.name} without asking for new "
            f"payment details")


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


# ---------------------------------------------------------------------------
# Sequential-value reasoning -- regression guards for real bugs
# ---------------------------------------------------------------------------


def test_acting_now_does_not_forfeit_the_future():
    """Waiting must not be preferred merely because a later moment is better.

    Regression guard for the bug that cost this agent the headline result. It
    compared "act now" against "act at the better moment" as mutually exclusive
    alternatives. They are not: if the retry fires now and fails, the better
    moment is still available afterwards. Treating them as exclusive made the
    agent defer itself past the payment's expiry.

    With a high success probability now and a cheap attempt, the agent must act
    rather than hold.
    """
    agent = KintsugiPolicy(retry_model=_StubModel(0.8),
                           nudge_model=_StubModel(0.05))
    action = agent.decide(
        _payment(FailureClass.RISK_DECLINE, amount=500_000), 10 * 60, None)
    assert action.kind is ActionKind.RETRY, (
        "a high-probability, low-cost action must be taken, not deferred")


def test_contact_fatigue_is_tracked_per_customer_not_per_payment():
    """Patience belongs to the person, not the invoice.

    Three separate payments from one customer must consume one shared contact
    budget. Tracking it per payment let a customer be messaged once per payment
    while each payment believed it had spent a single contact.
    """

    agent = KintsugiPolicy(retry_model=_StubModel(0.001),
                           nudge_model=_StubModel(0.9),
                           config=AgentConfig(max_contacts_per_customer=2))

    def other(pid: str) -> Payment:
        p = _payment(FailureClass.AUTH_ABANDONED, amount=5_000_000)
        p.payment_id = pid
        return p

    nudged = 0
    for i in range(6):
        action = agent.decide(other(f"pay_{i}"), 10 * 60 + i, None)
        if action.kind is ActionKind.NUDGE:
            nudged += 1
    assert nudged <= 2, (
        f"sent {nudged} messages to one customer against a cap of 2")


def test_calendar_boundary_features_are_present():
    """Daily limits reset at midnight; elapsed minutes cannot express that.

    23:50 to 00:10 is twenty minutes and a different day. Without an explicit
    calendar feature the model retried LIMIT_EXCEEDED failures inside the same
    day, where a daily limit cannot have reset.
    """
    from kintsugi.agent.features import extract, feature_names
    from kintsugi.domain import Rail

    names = feature_names()
    idx = names.index("same_calendar_day_as_last_attempt")

    payment = _payment(FailureClass.LIMIT_EXCEEDED)   # attempt at minute 0
    same_day = extract(payment, 23 * 60, Rail.UPI_INTENT)
    next_day = extract(payment, 25 * 60, Rail.UPI_INTENT)

    assert same_day[idx] == 1.0
    assert next_day[idx] == 0.0


# ---------------------------------------------------------------------------
# Scheme and regulator compliance
# ---------------------------------------------------------------------------


def test_autopay_windows_match_the_npci_rule():
    """Permitted: before 10:00, 13:00-17:00, after 21:30."""
    from kintsugi.compliance import in_autopay_window

    def at(h, m=0):
        return h * 60 + m

    assert in_autopay_window(at(9, 59))
    assert in_autopay_window(at(14))
    assert in_autopay_window(at(22))
    assert not in_autopay_window(at(10, 1))
    assert not in_autopay_window(at(12))
    assert not in_autopay_window(at(18))
    assert not in_autopay_window(at(21, 15))


def test_next_permitted_window_moves_forward_not_back():
    from kintsugi.compliance import in_autopay_window, next_autopay_window

    for hour in range(24):
        now = hour * 60 + 7
        nxt = next_autopay_window(now)
        assert nxt >= now
        assert in_autopay_window(nxt), f"{hour}:07 -> not a permitted window"


def test_mandate_retries_are_capped_at_the_npci_limit():
    from kintsugi.compliance import AUTOPAY_MAX_RETRIES, RuleBook
    from kintsugi.domain import Attempt

    payment = _payment(FailureClass.INSUFFICIENT_FUNDS, is_recurring=True)
    book = RuleBook()
    at = 9 * 60          # inside a permitted window
    assert book.check_retry(payment, at).allowed

    for i in range(AUTOPAY_MAX_RETRIES):
        payment.attempts.append(Attempt(
            attempt_no=i + 1, at=at, rail=payment.preferred_rail,
            succeeded=False, failure_class=FailureClass.INSUFFICIENT_FUNDS))
    assert not book.check_retry(payment, at).allowed


def test_scheme_prohibits_reattempting_a_terminal_decline():
    from kintsugi.compliance import RuleBook

    book = RuleBook()
    verdict = book.check_retry(_payment(FailureClass.CARD_BLOCKED), 9 * 60)
    assert verdict.violated
    assert verdict.fine_paise > 0


def test_compliant_policies_commit_no_violations():
    """The measurement that makes the compliance layer worth having.

    A naive fixed schedule breaches these rules constantly and its recovery
    rate never shows it. Both policies that implement the rules must come out
    at exactly zero.
    """
    world = World(WorldConfig(n_customers=600, n_payments=2500, seed=1000))
    for policy in (RuleBasedPolicy(), KintsugiPolicy(
            retry_model=_StubModel(0.5), nudge_model=_StubModel(0.2))):
        result = world.run(policy)
        assert result.compliance["violations"] == 0, (
            f"{policy.name} breached {result.compliance['violations']} times: "
            f"{result.compliance['by_rule']}")


def test_a_naive_schedule_does_breach_the_rules():
    """Guards the comparison: if this ever hits zero the layer is inert."""
    world = World(WorldConfig(n_customers=600, n_payments=2500, seed=1000))
    result = world.run(FixedRetryPolicy())
    assert result.compliance["violations"] > 0
    assert result.compliance["fines_paise"] > 0
