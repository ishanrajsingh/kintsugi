"""Invariants that would fail silently.

Every check here guards something that, if broken, would still produce a
plausible-looking number. A simulation that leaves payments open, or a harness
that finds a difference between a policy and itself, does not crash -- it
reports a slightly wrong result with full confidence. Those are the failures
worth spending tests on.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.agent.policy import (
    FixedRetryPolicy, NoRecoveryPolicy, RuleBasedPolicy,
)
from kintsugi.eval import metrics as M
from kintsugi.eval.harness import compare, evaluate
from kintsugi.world.simulator import World, WorldConfig

CFG = WorldConfig(n_customers=500, n_payments=2000, seed=77)


class _Stub:
    def __init__(self, p: float = 0.35) -> None:
        self.p = p

    def predict(self, x) -> float:
        return self.p

    def predict_batch(self, X) -> np.ndarray:
        return np.full(len(X), self.p)


def _agent() -> KintsugiPolicy:
    return KintsugiPolicy(retry_model=_Stub(0.4), nudge_model=_Stub(0.2))


@pytest.fixture(scope="module")
def world() -> World:
    return World(CFG)


@pytest.fixture(scope="module")
def run(world):
    return world.run(_agent())


# ---------------------------------------------------------------------------
# Simulation bookkeeping
# ---------------------------------------------------------------------------


def test_every_payment_ends_exactly_one_way(run):
    """Recovered or abandoned, never both, never neither.

    A payment left open at the horizon is silently excluded from recovery
    without being counted as a loss, which flatters whichever policy leaves
    the most work unfinished.
    """
    both = [p for p in run.payments if p.recovered_at and p.abandoned_at]
    neither = [p for p in run.payments if p.is_open]
    assert not both, f"{len(both)} payments both recovered and abandoned"
    assert not neither, f"{len(neither)} payments left open at the horizon"


def test_a_recovery_has_exactly_one_success_and_it_is_last(run):
    """Money arrives once, and nothing is attempted afterwards."""
    checked = 0
    for payment in run.payments:
        if not payment.is_recovered:
            continue
        checked += 1
        succeeded = [i for i, a in enumerate(payment.attempts) if a.succeeded]
        assert len(succeeded) == 1, f"{payment.payment_id}: {len(succeeded)} successes"
        assert succeeded[0] == len(payment.attempts) - 1, (
            f"{payment.payment_id}: attempted again after succeeding")
    assert checked > 0


def test_attempts_are_chronological_and_follow_the_payment(run):
    for payment in run.payments:
        times = [a.at for a in payment.attempts]
        assert times == sorted(times), f"{payment.payment_id}: out of order"
        if times:
            assert times[0] >= payment.created_at


def test_recovery_never_predates_the_attempt_that_caused_it(run):
    for payment in run.payments:
        if payment.is_recovered and payment.attempts:
            assert payment.recovered_at >= payment.attempts[-1].at


def test_metric_identities_hold(run):
    m = M.compute(run)
    assert 0 <= m.recovered <= m.failed_first_attempt
    assert m.total_cost_paise >= 0
    assert 0.0 <= m.recovery_rate <= 1.0
    assert 0.0 <= m.gmv_recovery_rate <= 1.0


def test_a_policy_is_deterministic(world):
    a = M.compute(world.run(RuleBasedPolicy()))
    b = M.compute(world.run(RuleBasedPolicy()))
    assert (a.recovered, a.retries, a.nudges) == (b.recovered, b.retries, b.nudges)


def test_the_floor_policy_never_acts(world):
    result = world.run(NoRecoveryPolicy())
    assert not any(p.retry_count or p.nudge_count for p in result.payments)


# ---------------------------------------------------------------------------
# Evaluation machinery
# ---------------------------------------------------------------------------


def test_comparing_a_policy_with_itself_is_exactly_null():
    """The harness must find no difference where there is none.

    If this ever returns a non-zero effect, every reported lift is inflated by
    whatever noise the pairing failed to cancel -- and nothing else in the
    suite would notice.
    """
    results = evaluate([RuleBasedPolicy(), FixedRetryPolicy()],
                       replace(CFG, n_payments=1500), n_seeds=4, progress=False)
    c = compare(results, "rule_based", "rule_based", "net_value_paise")
    assert c.mean_diff == pytest.approx(0.0, abs=1e-9)
    assert c.p_value > 0.99
    assert not c.significant


# ---------------------------------------------------------------------------
# Compliance, on seeds nobody tuned against
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [5, 55, 555])
def test_the_agent_never_breaches_scheme_rules_on_any_seed(seed):
    """Compliance measured on one seed is an anecdote, not a guarantee."""
    result = World(replace(CFG, seed=seed)).run(_agent())
    assert result.compliance["violations"] == 0, (
        f"seed {seed}: {result.compliance['by_rule']}")


# ---------------------------------------------------------------------------
# The no-model claim, tested rather than asserted
# ---------------------------------------------------------------------------


def test_everything_works_with_no_model_and_no_cache(tmp_path):
    """"The system runs correctly with no model at all" is a claim, so test it.

    Cold start specifically: no provider *and* no warm cache. A populated cache
    makes this pass for the wrong reason -- it serves previously generated copy
    and never exercises the fallback at all, which is how the first version of
    this check fooled itself.
    """
    from kintsugi.agent.messaging import MessageWriter, validate
    from kintsugi.domain import Channel, FailureClass
    from kintsugi.taxonomy.classifier import TaxonomyResolver
    from kintsugi.taxonomy.providers import NullProvider

    cache = tmp_path / "empty.json"
    writer = MessageWriter(provider=NullProvider(), cache_path=cache)

    for cause in FailureClass:
        for channel in Channel:
            message = writer.write(cause, channel, 125_000, merchant="Acme")
            assert message.source == "template", (
                f"{cause.name}/{channel.name} did not fall back to a template")
            assert message.text and "{" not in message.text, (
                f"{cause.name}/{channel.name}: empty or unfilled placeholder")
            needs_link = cause.disposition.name in ("NEEDS_CUSTOMER", "TERMINAL")
            problem = validate(
                message.text.replace("pay.example.in/r/xxxx", "{link}"),
                channel, needs_link)
            assert problem is None, (
                f"{cause.name}/{channel.name} template fails its own "
                f"validator: {problem}")

    resolver = TaxonomyResolver(provider=NullProvider(), cache_path=cache)
    assert resolver.classify("51 - Insufficient funds").failure_class is (
        FailureClass.INSUFFICIENT_FUNDS)
    assert resolver.classify("a string no rule has ever seen").failure_class is (
        FailureClass.UNKNOWN)


def test_a_missing_predictor_falls_back_to_a_valid_probability(tmp_path):
    """A model file that is absent must not crash or return nonsense."""
    import numpy as np

    from kintsugi.agent.features import N_FEATURES
    from kintsugi.agent.predictor import Predictor

    p = Predictor.load("not_a_real_model", directory=tmp_path)
    value = p.predict(np.zeros(N_FEATURES, dtype=np.float32))
    assert 0.0 <= value <= 1.0
