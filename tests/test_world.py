"""Tests for the simulated world.

These concentrate on the properties the evaluation *depends* on. If any of
these break, the headline numbers stop meaning what they claim to mean, and
they would break silently -- a broken common-random-numbers guarantee still
produces confident-looking confidence intervals.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from kintsugi.agent.policy import FixedRetryPolicy, NoRecoveryPolicy, RuleBasedPolicy
from kintsugi.domain import Disposition, FailureClass, Rail
from kintsugi.world.customers import Customer
from kintsugi.world.simulator import TERMINAL_CLASSES, World, WorldConfig

SMALL = WorldConfig(n_customers=400, n_payments=1500, seed=42)


@pytest.fixture(scope="module")
def world() -> World:
    return World(SMALL)


# ---------------------------------------------------------------------------
# Determinism and common random numbers
# ---------------------------------------------------------------------------


def test_same_seed_reproduces_the_world():
    a = World(SMALL).run(NoRecoveryPolicy())
    b = World(SMALL).run(NoRecoveryPolicy())
    assert [p.payment_id for p in a.payments] == [p.payment_id for p in b.payments]
    assert [p.amount_paise for p in a.payments] == [p.amount_paise for p in b.payments]
    assert ([p.attempts[0].succeeded for p in a.payments]
            == [p.attempts[0].succeeded for p in b.payments])


def test_different_seeds_produce_different_worlds():
    a = World(SMALL).run(NoRecoveryPolicy())
    b = World(replace(SMALL, seed=43)).run(NoRecoveryPolicy())
    assert ([p.attempts[0].succeeded for p in a.payments]
            != [p.attempts[0].succeeded for p in b.payments])


def test_first_attempt_is_identical_across_policies(world):
    """The core CRN guarantee the paired evaluation rests on.

    A policy is only consulted *after* a failure, so it cannot influence the
    initial authorisation. If these ever diverge, randomness is leaking through
    call order and every paired interval downstream is wrong.
    """
    signatures = []
    for policy in (NoRecoveryPolicy(), FixedRetryPolicy(), RuleBasedPolicy()):
        result = world.run(policy)
        signatures.append({
            p.payment_id: (p.attempts[0].succeeded, p.attempts[0].failure_class)
            for p in result.payments
        })
    assert signatures[0] == signatures[1] == signatures[2]


def test_policy_cannot_change_payment_population(world):
    a = world.run(NoRecoveryPolicy())
    b = world.run(RuleBasedPolicy())
    assert len(a.payments) == len(b.payments)
    assert ([p.amount_paise for p in a.payments]
            == [p.amount_paise for p in b.payments])


# ---------------------------------------------------------------------------
# Latent-gate semantics: the physics the whole result depends on
# ---------------------------------------------------------------------------


def test_a_terminal_failure_never_recovers_on_the_same_instrument(world):
    """A dead instrument stays dead -- but the customer is not the instrument.

    The invariant is not "terminal failures never recover". They can, by two
    routes that both replace the credential: the customer supplies new details
    after being asked, or a card-network account updater pushes refreshed ones.
    What must never happen is a terminal failure recovering while still sitting
    on the instrument that was declared dead.
    """
    result = world.run(FixedRetryPolicy(
        retry_offsets=(30, 60, 120, 240, 480), nudge_offsets=(45, 90)))
    checked = recovered = 0
    for payment in result.payments:
        first = payment.attempts[0]
        if first.succeeded or first.failure_class not in TERMINAL_CLASSES:
            continue
        checked += 1
        if payment.is_recovered:
            recovered += 1
            assert payment.credentials_updated, (
                f"{payment.payment_id} recovered from "
                f"{first.failure_class.name} on the original instrument")
    assert checked > 0, "no terminal failures in sample; test proves nothing"
    assert recovered < checked * 0.5, (
        "terminal failures are recovering too easily to be terminal")


def test_insufficient_funds_gate_is_stable_within_a_day(world):
    """Retrying a balance failure the same day must draw the same outcome.

    This is the property that stops a blind retry loop from beating an
    intelligent policy. If this test fails, retries succeed on a fresh roll and
    the entire evaluation becomes a measure of how often a policy retries.
    """
    target = None
    for payment in world._template:
        ok, cause = world.resolve_attempt(
            payment, payment.preferred_rail, payment.created_at, 0)
        if not ok and cause is FailureClass.INSUFFICIENT_FUNDS:
            target = payment
            break
    assert target is not None, "no balance failure found in sample"

    day_start = (target.created_at // 1440) * 1440
    for offset in (10, 60, 300, 900):
        at = day_start + offset
        if at // 1440 != target.created_at // 1440:
            continue
        _, cause = world.resolve_attempt(target, target.preferred_rail, at, 1)
        assert cause is FailureClass.INSUFFICIENT_FUNDS, (
            "balance gate re-rolled within the same day")


def test_mandates_have_no_customer_present_failures(world):
    """Server-initiated debits cannot be abandoned: nobody is there."""
    result = world.run(NoRecoveryPolicy())
    for payment in result.payments:
        if not payment.is_recurring:
            continue
        for attempt in payment.attempts:
            assert attempt.failure_class not in {
                FailureClass.AUTH_ABANDONED,
                FailureClass.AUTH_TIMEOUT,
                FailureClass.USER_CANCELLED,
            }


def test_nudges_do_not_conjure_money(world):
    """A reminder produces an attempt, not a recovery.

    Guards the bug that made naive dunning look excellent: nudges used to mark
    a payment recovered directly, so a reminder could 'recover' a customer with
    no balance and even one whose card was blocked.
    """
    result = world.run(FixedRetryPolicy(
        retry_offsets=(), nudge_offsets=(30, 120, 600)))
    for payment in result.payments:
        if payment.is_recovered:
            assert any(a.succeeded for a in payment.attempts), (
                f"{payment.payment_id} recovered with no successful attempt")


# ---------------------------------------------------------------------------
# Customer model
# ---------------------------------------------------------------------------


def test_liquidity_peaks_after_payday():
    customer = Customer(
        customer_id="c", issuer_code="MRDN", liquidity_base=0.4,
        salary_day=0, typical_amount_paise=100_000, peak_hour=18)
    on_payday = customer.liquidity_at(0)
    late_month = customer.liquidity_at(25 * 1440)
    assert on_payday > late_month


def test_larger_amounts_are_likelier_to_bounce():
    customer = Customer(
        customer_id="c", issuer_code="MRDN", liquidity_base=0.5,
        salary_day=0, typical_amount_paise=100_000, peak_hour=18)
    small = customer.p_insufficient(20 * 1440, 10_000, scale=1.0)
    large = customer.p_insufficient(20 * 1440, 1_000_000, scale=1.0)
    assert large > small


def test_checkout_selection_bonus_reduces_bounce_rate():
    """Choosing to pay is evidence of being able to pay."""
    customer = Customer(
        customer_id="c", issuer_code="MRDN", liquidity_base=0.5,
        salary_day=0, typical_amount_paise=100_000, peak_hour=18)
    scheduled = customer.p_insufficient(20 * 1440, 100_000, 1.0, 0.0)
    chosen = customer.p_insufficient(20 * 1440, 100_000, 1.0, 0.62)
    assert chosen < scheduled


def test_attention_is_low_overnight():
    customer = Customer(
        customer_id="c", issuer_code="MRDN", liquidity_base=0.7,
        salary_day=0, typical_amount_paise=100_000, peak_hour=19)
    evening = customer.attention_at(19 * 60)
    small_hours = customer.attention_at(3 * 60)
    assert evening > small_hours * 3


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------


def test_every_failure_class_has_a_disposition():
    for fc in FailureClass:
        assert isinstance(fc.disposition, Disposition)


def test_terminal_classes_agree_with_disposition():
    for fc in TERMINAL_CLASSES:
        assert fc.is_terminal
        assert fc.disposition is Disposition.TERMINAL


def test_rails_that_need_a_customer():
    assert Rail.UPI_COLLECT.requires_customer_present
    assert not Rail.CARD.requires_customer_present
    assert not Rail.WALLET.requires_customer_present
