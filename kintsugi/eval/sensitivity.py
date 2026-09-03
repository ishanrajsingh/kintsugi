"""Does the result survive the assumptions it was built on?

The fair objection to this whole project is that the world is ours, so the lift
might be an artefact of a number we chose. The answer is not to argue; it is to
re-run the comparison with those numbers moved and show what happens.

Every constant swept here carries ``Provenance.ASSUMPTION`` in
:mod:`kintsugi.calibration` -- these are exactly the values with no published
source behind them. Each is pushed well below and well above its default,
including to settings actively hostile to the agent (retries nearly free, so
blind retrying costs little; reminders highly effective, so naive dunning works;
customers infinitely patient, so over-contacting is harmless).

A lift that only exists at one setting is not a result. What this reports is
the *distribution* of the lift across the assumption space, and it reports the
cases where the agent does worse just as loudly as the cases where it does
better.

Two groups, because they are not equally clean:

**Behavioural** constants (nudge effectiveness, patience, churn, retry cost)
do not enter the first-attempt gates at all, so the world stays exactly as
calibrated and only the recovery dynamics change.

**Structural** constants (outage frequency, recurring share) do shift the
first-attempt marginals, so a swept world is no longer precisely fitted to the
published targets. The realised drift is measured and reported alongside the
lift rather than glossed over.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from kintsugi import calibration as cal
from kintsugi.calibration import Sourced
from kintsugi.eval.harness import compare, evaluate
from kintsugi.world.simulator import WorldConfig


@dataclass
class Perturbation:
    """One assumption, moved."""

    label: str
    group: str
    apply: Callable[[], Callable[[], None]]
    """Applies the change and returns an undo callable."""
    note: str = ""


def _set_constant(name: str, value) -> Callable[[], Callable[[], None]]:
    """Swap a calibration constant, preserving its provenance wrapper."""
    def apply() -> Callable[[], None]:
        original: Sourced = getattr(cal, name)
        setattr(cal, name, Sourced(
            value, original.provenance, original.source,
            f"{original.note} [swept to {value}]"))
        def undo() -> None:
            setattr(cal, name, original)
        return undo
    return apply


def _config_change(**kwargs) -> Callable[[], Callable[[], None]]:
    """Sweep a world-configuration field instead of a constant."""
    def apply() -> Callable[[], None]:
        _CONFIG_OVERRIDES.update(kwargs)
        def undo() -> None:
            for k in kwargs:
                _CONFIG_OVERRIDES.pop(k, None)
        return undo
    return apply


_CONFIG_OVERRIDES: dict = {}


def default_perturbations() -> list[Perturbation]:
    return [
        # --- behavioural: calibration unaffected -------------------------
        Perturbation("nudge_conversion 0.10 (half)", "behavioural",
                     _set_constant("NUDGE_CONVERSION_BASE", 0.10),
                     "reminders much weaker than assumed"),
        Perturbation("nudge_conversion 0.40 (double)", "behavioural",
                     _set_constant("NUDGE_CONVERSION_BASE", 0.40),
                     "hostile: reminders very effective, so naive dunning wins"),
        Perturbation("patience 1.2 (impatient)", "behavioural",
                     _set_constant("BASE_PATIENCE", 1.2),
                     "customers tire of contact quickly"),
        Perturbation("patience 6.0 (tolerant)", "behavioural",
                     _set_constant("BASE_PATIENCE", 6.0),
                     "hostile: over-contacting is nearly free"),
        Perturbation("churn_hazard 0.05 (mild)", "behavioural",
                     _set_constant("CHURN_HAZARD_AT_ZERO_PATIENCE", 0.05),
                     "hostile: little penalty for hounding customers"),
        Perturbation("churn_hazard 0.45 (severe)", "behavioural",
                     _set_constant("CHURN_HAZARD_AT_ZERO_PATIENCE", 0.45),
                     "over-contact drives customers away hard"),
        Perturbation("retry_cost 2p (near free)", "behavioural",
                     _set_constant("RETRY_ATTEMPT_COST_PAISE", 2),
                     "hostile: brute-force retrying is nearly costless"),
        Perturbation("retry_cost 100p (expensive)", "behavioural",
                     _set_constant("RETRY_ATTEMPT_COST_PAISE", 100),
                     "each attempt materially costly"),
        Perturbation("nudge_decay 0.85 (slow)", "behavioural",
                     _set_constant("NUDGE_DECAY", 0.85),
                     "hostile: repeat reminders keep working"),
        Perturbation("salary_window 2d (sharp)", "behavioural",
                     _set_constant("SALARY_REPLENISH_WINDOW_DAYS", 2),
                     "balance recovers in a sharp spike"),
        Perturbation("salary_window 20d (flat)", "behavioural",
                     _set_constant("SALARY_REPLENISH_WINDOW_DAYS", 20),
                     "hostile: almost no payday signal to exploit"),

        # --- structural: shifts first-attempt marginals ------------------
        Perturbation("outage_rate 0.01 (rare)", "structural",
                     _set_constant("ISSUER_OUTAGE_RATE_PER_DAY", 0.01),
                     "hostile: little issuer downtime to detect"),
        Perturbation("outage_rate 0.15 (frequent)", "structural",
                     _set_constant("ISSUER_OUTAGE_RATE_PER_DAY", 0.15),
                     "unstable issuers"),
        Perturbation("recurring share 0.10", "structural",
                     _config_change(mandate_share=0.10),
                     "hostile: little recurring volume, where the value is"),
        Perturbation("recurring share 0.55", "structural",
                     _config_change(mandate_share=0.55),
                     "subscription-heavy book"),
    ]


@dataclass
class SweepResult:
    label: str
    group: str
    note: str
    lift_relative: float
    lift_absolute: float
    ci_low: float
    ci_high: float
    significant: bool
    baseline_mean: float
    challenger_mean: float
    checkout_success: float = 0.0
    mandate_success: float = 0.0

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "group": self.group,
            "note": self.note,
            "lift_relative": self.lift_relative,
            "lift_absolute_paise": self.lift_absolute,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "significant": self.significant,
            "baseline_mean": self.baseline_mean,
            "challenger_mean": self.challenger_mean,
            "realised_checkout_success": self.checkout_success,
            "realised_mandate_success": self.mandate_success,
        }


def run_sweep(
    policy_factory: Callable[[], list],
    config: WorldConfig,
    baseline: str = "rule_based",
    challenger: str = "kintsugi",
    metric: str = "net_value_paise",
    n_seeds: int = 10,
    perturbations: list[Perturbation] | None = None,
    verbose: bool = True,
) -> list[SweepResult]:
    """Re-run the paired comparison under each perturbed assumption.

    ``policy_factory`` must return *fresh* policy instances each call, since a
    policy carries state (the health monitor) that must not leak between worlds.
    """
    perturbations = perturbations or default_perturbations()
    results: list[SweepResult] = []

    baseline_row = _one(policy_factory, config, baseline, challenger, metric,
                        n_seeds, Perturbation("(unperturbed)", "reference",
                                              lambda: (lambda: None),
                                              "default assumptions"))
    results.append(baseline_row)
    if verbose:
        print(f"  {baseline_row.label:34s} {baseline_row.lift_relative:+7.2%}"
              f"  {'sig' if baseline_row.significant else '---'}")

    for perturbation in perturbations:
        row = _one(policy_factory, config, baseline, challenger, metric,
                   n_seeds, perturbation)
        results.append(row)
        if verbose:
            print(f"  {row.label:34s} {row.lift_relative:+7.2%}"
                  f"  {'sig' if row.significant else '---'}  [{row.group}]")
    return results


def _one(policy_factory, config, baseline, challenger, metric, n_seeds,
         perturbation) -> SweepResult:
    undo = perturbation.apply()
    try:
        cfg = replace(config, **_CONFIG_OVERRIDES) if _CONFIG_OVERRIDES else config
        results = evaluate(policy_factory(), cfg, n_seeds=n_seeds, progress=False)
        comparison = compare(results, baseline, challenger, metric)
        checkout, mandate = _realised_rates(cfg)
        return SweepResult(
            label=perturbation.label,
            group=perturbation.group,
            note=perturbation.note,
            lift_relative=comparison.relative_lift,
            lift_absolute=comparison.mean_diff,
            ci_low=comparison.ci_low,
            ci_high=comparison.ci_high,
            significant=comparison.significant,
            baseline_mean=comparison.baseline_mean,
            challenger_mean=comparison.challenger_mean,
            checkout_success=checkout,
            mandate_success=mandate,
        )
    finally:
        undo()


def _realised_rates(config) -> tuple[float, float]:
    """First-attempt authorisation under the perturbed world.

    Reported so a reader can see when a structural sweep has pushed the world
    away from the published calibration targets, and discount accordingly.
    """
    from kintsugi.world.fitting import measure
    from kintsugi.world.simulator import World

    stats = measure(World(replace(config, n_payments=min(config.n_payments, 8000))))
    return stats["checkout_success"], stats["mandate_success"]


def summarise(results: list[SweepResult]) -> dict:
    """Headline robustness statistics."""
    swept = [r for r in results if r.group != "reference"]
    positive = [r for r in swept if r.lift_relative > 0]
    significant_positive = [r for r in swept if r.significant and r.lift_relative > 0]
    negative_significant = [
        r for r in swept if r.significant and r.lift_relative < 0]
    lifts = sorted(r.lift_relative for r in swept)
    return {
        "n_perturbations": len(swept),
        "positive": len(positive),
        "significant_positive": len(significant_positive),
        "significant_negative": len(negative_significant),
        "min_lift": lifts[0] if lifts else 0.0,
        "median_lift": lifts[len(lifts) // 2] if lifts else 0.0,
        "max_lift": lifts[-1] if lifts else 0.0,
        "regressions": [r.label for r in negative_significant],
    }
