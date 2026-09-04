"""Paired policy evaluation with common random numbers.

For each seed we build one world and run every policy against it. Because the
simulator's randomness is counter-based (kintsugi.rng), the k-th attempt on
payment P resolves against the same underlying draw no matter which policy made
it. The policies don't face statistically similar worlds, they face the *same*
world, payment by payment. Differences get paired and the shared noise that
dominates a naive A/B cancels.

That's the difference between "policy A recovered 3% more in my run" and "the
paired difference is 3.1%, 95% interval 2.6-3.6%".

CRN is easy to break by accident -- one stray unkeyed draw and the pairing
degrades into an ordinary noisy comparison while the confidence intervals keep
printing as if nothing happened. So verify_crn() asserts that every policy saw
byte-identical first attempts on every payment, and the evaluation refuses to
report if that fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, Sequence

import numpy as np

from kintsugi.eval import metrics as M
from kintsugi.world.simulator import SimulationResult, World, WorldConfig


@dataclass(slots=True)
class SeedResult:
    seed: int
    by_policy: dict[str, M.RunMetrics]
    raw: dict[str, SimulationResult] = field(repr=False, default_factory=dict)


@dataclass(slots=True)
class PairedComparison:
    """One challenger against one baseline, on a single metric."""

    baseline: str
    challenger: str
    metric: str
    baseline_mean: float
    challenger_mean: float
    diffs: np.ndarray = field(repr=False)
    mean_diff: float = 0.0
    ci_low: float = 0.0
    ci_high: float = 0.0
    win_rate: float = 0.0
    p_value: float = 1.0

    @property
    def relative_lift(self) -> float:
        return self.mean_diff / abs(self.baseline_mean) if self.baseline_mean else 0.0

    @property
    def significant(self) -> bool:
        """Interval excludes zero."""
        return (self.ci_low > 0) or (self.ci_high < 0)

    def describe(self) -> str:
        arrow = "+" if self.mean_diff >= 0 else ""
        sig = "" if self.significant else "  (not significant)"
        return (
            f"{self.challenger} vs {self.baseline} [{self.metric}]: "
            f"{arrow}{self.relative_lift:.2%} "
            f"(95% CI {self.ci_low:+.4g} to {self.ci_high:+.4g}, "
            f"wins {self.win_rate:.0%} of seeds, p={self.p_value:.4f}){sig}"
        )


def run_seed(
    seed: int,
    policies: Sequence,
    config: WorldConfig,
    keep_raw: bool = False,
) -> SeedResult:
    """Run every policy against one shared world."""
    cfg = replace(config, seed=seed)
    world = World(cfg)

    by_policy: dict[str, M.RunMetrics] = {}
    raw: dict[str, SimulationResult] = {}
    for policy in policies:
        result = world.run(policy)
        name = getattr(policy, "name", type(policy).__name__)
        by_policy[name] = M.compute(result)
        if keep_raw:
            raw[name] = result
    return SeedResult(seed=seed, by_policy=by_policy, raw=raw)


def verify_crn(seed: int, policies: Sequence, config: WorldConfig) -> dict:
    """Confirm the pairing holds: identical first attempts across policies.

    A policy cannot influence the initial authorisation -- it is only consulted
    after a failure -- so if common random numbers are working, every policy
    must observe exactly the same first outcome and the same decline string on
    every payment. Any divergence means randomness is leaking through call
    order, and the paired intervals downstream would be quietly wrong.
    """
    cfg = replace(config, seed=seed)
    world = World(cfg)

    signature: dict[str, tuple] | None = None
    mismatches = 0
    checked = 0

    for policy in policies:
        result = world.run(policy)
        sig = {
            p.payment_id: (
                p.attempts[0].succeeded,
                p.attempts[0].failure_class,
                p.attempts[0].raw_error,
            )
            for p in result.payments if p.attempts
        }
        if signature is None:
            signature = sig
            checked = len(sig)
        else:
            mismatches += sum(
                1 for k, v in sig.items() if signature.get(k) != v)

    return {
        "payments_checked": checked,
        "policies": len(policies),
        "mismatches": mismatches,
        "crn_intact": mismatches == 0,
    }


def evaluate(
    policies: Sequence,
    config: WorldConfig,
    seeds: Sequence[int] | None = None,
    n_seeds: int = 30,
    progress: bool = True,
) -> list[SeedResult]:
    """Run every policy across many independent worlds."""
    if seeds is None:
        seeds = [1000 + 7 * i for i in range(n_seeds)]

    check = verify_crn(seeds[0], policies, config)
    if not check["crn_intact"]:
        raise RuntimeError(
            f"Common random numbers are broken: {check['mismatches']} of "
            f"{check['payments_checked']} payments differed on their first "
            f"attempt across policies. Paired comparison would be invalid."
        )

    results: list[SeedResult] = []
    for i, seed in enumerate(seeds):
        results.append(run_seed(seed, policies, config))
        if progress and (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(seeds)} seeds")
    return results


def compare(
    results: Sequence[SeedResult],
    baseline: str,
    challenger: str,
    metric: str = "net_value_paise",
    n_bootstrap: int = 20_000,
    rng_seed: int = 0,
) -> PairedComparison:
    """Paired bootstrap of ``challenger - baseline`` on one metric.

    Resampling is over *seeds*, not payments, because payments within a world
    are not independent -- they share issuer incidents and, often, customers.
    Bootstrapping the seed-level paired differences respects that structure.
    """
    getter = _metric_getter(metric)
    base = np.array([getter(r.by_policy[baseline]) for r in results], dtype=float)
    chal = np.array([getter(r.by_policy[challenger]) for r in results], dtype=float)
    diffs = chal - base

    rng = np.random.default_rng(rng_seed)
    n = len(diffs)
    idx = rng.integers(0, n, size=(n_bootstrap, n))
    boot_means = diffs[idx].mean(axis=1)

    ci_low, ci_high = np.percentile(boot_means, [2.5, 97.5])

    # Two-sided bootstrap p-value: how often a mean-centred resample reaches
    # the observed effect. Cheap, assumption-light, and honest about ties.
    centred = boot_means - diffs.mean()
    p = float((np.abs(centred) >= abs(diffs.mean())).mean())

    return PairedComparison(
        baseline=baseline,
        challenger=challenger,
        metric=metric,
        baseline_mean=float(base.mean()),
        challenger_mean=float(chal.mean()),
        diffs=diffs,
        mean_diff=float(diffs.mean()),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        win_rate=float((diffs > 0).mean()),
        p_value=p,
    )


def _metric_getter(metric: str) -> Callable[[M.RunMetrics], float]:
    def get(m: M.RunMetrics) -> float:
        value = getattr(m, metric)
        return float(value)
    return get


def summary_table(
    results: Sequence[SeedResult], metrics: Sequence[str] | None = None
) -> dict[str, dict[str, float]]:
    """Mean of each metric per policy, across seeds."""
    if metrics is None:
        metrics = (
            "recovery_rate", "gmv_recovery_rate", "net_value_paise",
            "recovered_gmv_paise", "total_cost_paise", "retries", "nudges",
            "retries_per_recovery", "contacts_per_recovery",
            "wasted_retries", "churned",
        )
    policies = list(results[0].by_policy)
    table: dict[str, dict[str, float]] = {}
    for name in policies:
        row: dict[str, float] = {}
        for metric in metrics:
            vals = [float(getattr(r.by_policy[name], metric)) for r in results]
            finite = [v for v in vals if np.isfinite(v)]
            row[metric] = float(np.mean(finite)) if finite else float("nan")
        table[name] = row
    return table
