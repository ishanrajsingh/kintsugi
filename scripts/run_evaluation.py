"""Run the full evaluation and write the results the report is built from.

Produces ``data/results.json``: the paired policy comparison, the per-cause
breakdown, detector scores, taxonomy accuracy, model calibration, and the
calibration provenance table. Everything the write-up claims is generated here,
so nothing in the report is a number typed in by hand.

Run: ``python -m scripts.run_evaluation [--seeds N] [--payments N]``
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from kintsugi import calibration as cal
from kintsugi.agent.health_monitor import IssuerHealthMonitor, score_detection
from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.agent.policy import (
    FixedRetryPolicy, NoRecoveryPolicy, RuleBasedPolicy,
)
from kintsugi.agent.predictor import Predictor
from kintsugi.eval import metrics as M
from kintsugi.eval.harness import compare, evaluate, summary_table, verify_crn
from kintsugi.world.simulator import World, WorldConfig

RESULTS_PATH = Path(__file__).resolve().parents[1] / "data" / "results.json"

HEADLINE_METRICS = (
    "net_value_paise", "recovery_rate", "gmv_recovery_rate",
    "recovered_gmv_paise", "total_cost_paise", "retries", "nudges",
    "wasted_retries", "churned", "retries_per_recovery",
    "contacts_per_recovery",
)


def make_policies() -> list:
    """Fresh instances each call: policies carry per-run state."""
    return [
        NoRecoveryPolicy(),
        FixedRetryPolicy(),
        RuleBasedPolicy(),
        KintsugiPolicy(),
    ]


def detector_scores(config: WorldConfig, seeds: list[int]) -> dict:
    """Score the health monitor on seeds disjoint from its tuning set."""
    agg = {"precision": [], "recall": [], "latency": []}
    strata: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for seed in seeds:
        world = World(replace(config, seed=seed))
        policy = KintsugiPolicy()
        world.run(policy)
        score = score_detection(policy.monitor, world.issuers)
        agg["precision"].append(score.precision)
        agg["recall"].append(score.recall)
        if score.latencies:
            agg["latency"].append(score.median_latency)
        for label, row in score.by_duration.items():
            strata[label][0] += row["detected"]
            strata[label][1] += row["incidents"]

    mean = lambda xs: sum(xs) / len(xs) if xs else float("nan")  # noqa: E731
    return {
        "seeds": seeds,
        "precision": mean(agg["precision"]),
        "recall": mean(agg["recall"]),
        "median_detection_latency_min": mean(agg["latency"]),
        "recall_by_incident_duration": {
            k: {"detected": v[0], "incidents": v[1],
                "recall": v[0] / v[1] if v[1] else float("nan")}
            for k, v in sorted(strata.items())
        },
    }


def taxonomy_scores() -> dict:
    """Rule accuracy, and what the model adds on strings rules never saw."""
    from kintsugi.taxonomy import rules
    from kintsugi.taxonomy.classifier import TaxonomyResolver
    from kintsugi.taxonomy.codes import all_strings, catalogue_stats

    rule_cov = rules.coverage()

    # Offline only: uses whatever is already cached, never calls a model here,
    # so the evaluation stays fast and deterministic.
    resolver = TaxonomyResolver(use_llm=False)
    cached = {}
    for text, truth, is_holdout in all_strings():
        key = text.strip().lower()
        if key in resolver.cache:
            cached[text] = (resolver.cache[key], truth.name, is_holdout)

    holdout_rows = [v for v in cached.values() if v[2]]
    holdout_correct = sum(1 for pred, truth, _ in holdout_rows if pred == truth)

    return {
        "catalogue": catalogue_stats(),
        "rules": {
            "visible_accuracy": rule_cov["visible"]["accuracy"],
            "visible_n": rule_cov["visible"]["n"],
            "holdout_accuracy": rule_cov["holdout"]["accuracy"],
            "holdout_n": rule_cov["holdout"]["n"],
            "holdout_unmatched": rule_cov["holdout"]["unmatched"],
        },
        "llm_on_holdout": {
            "resolved": len(holdout_rows),
            "correct": holdout_correct,
            "accuracy": (holdout_correct / len(holdout_rows)
                         if holdout_rows else None),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=25)
    parser.add_argument("--payments", type=int, default=12_000)
    parser.add_argument("--customers", type=int, default=3_000)
    args = parser.parse_args()

    config = WorldConfig(
        n_customers=args.customers, n_payments=args.payments)

    print(f"Kintsugi evaluation: {args.seeds} worlds x {args.payments:,} payments")
    print("=" * 68)

    policies = make_policies()
    print("\n[1/5] Verifying common random numbers...")
    crn = verify_crn(1000, policies, config)
    print(f"      {crn['payments_checked']:,} payments, {crn['policies']} policies, "
          f"{crn['mismatches']} mismatches -> "
          f"{'PAIRED' if crn['crn_intact'] else 'BROKEN'}")
    if not crn["crn_intact"]:
        raise SystemExit("CRN broken; refusing to report paired statistics.")

    print(f"\n[2/5] Running {args.seeds} paired worlds...")
    t0 = time.time()
    results = evaluate(make_policies(), config, n_seeds=args.seeds)
    print(f"      done in {time.time() - t0:.0f}s")

    table = summary_table(results, HEADLINE_METRICS)

    print("\n[3/5] Paired comparisons...")
    comparisons = []
    pairs = [("fixed_retry", "rule_based"), ("fixed_retry", "kintsugi"),
             ("rule_based", "kintsugi")]
    for base, chal in pairs:
        for metric in ("net_value_paise", "recovery_rate", "gmv_recovery_rate",
                       "total_cost_paise", "nudges", "wasted_retries"):
            c = compare(results, base, chal, metric)
            comparisons.append({
                "baseline": base, "challenger": chal, "metric": metric,
                "baseline_mean": c.baseline_mean,
                "challenger_mean": c.challenger_mean,
                "mean_diff": c.mean_diff,
                "relative_lift": c.relative_lift,
                "ci_low": c.ci_low, "ci_high": c.ci_high,
                "win_rate": c.win_rate, "p_value": c.p_value,
                "significant": c.significant,
            })
            if metric == "net_value_paise":
                print(f"      {c.describe()}")

    print("\n[4/5] Per-cause breakdown...")
    world = World(replace(config, seed=1000))
    by_cause: dict[str, dict] = {}
    for policy in make_policies():
        result = world.run(policy)
        by_cause[result.policy_name] = M.by_failure_class(result)

    print("\n[5/5] Detector, taxonomy, and model reports...")
    detector = detector_scores(
        replace(config, n_payments=max(args.payments, 40_000)),
        [101, 102, 103])
    print(f"      detector: precision {detector['precision']:.1%}, "
          f"recall {detector['recall']:.1%}")

    taxonomy = taxonomy_scores()
    print(f"      taxonomy rules: {taxonomy['rules']['visible_accuracy']:.0%} visible, "
          f"{taxonomy['rules']['holdout_accuracy']:.0%} held-out")

    model_report_path = Path(__file__).resolve().parents[1] / "data" / "model_report.json"
    models = json.loads(model_report_path.read_text()) if model_report_path.exists() else {}

    fitted_path = Path(__file__).resolve().parents[1] / "data" / "fitted_scales.json"
    fit = json.loads(fitted_path.read_text()).get("fit_report", {}) \
        if fitted_path.exists() else {}

    payload = {
        "config": {
            "seeds": args.seeds,
            "payments_per_world": args.payments,
            "customers_per_world": args.customers,
            "horizon_days": config.horizon_days,
            "mandate_share": config.mandate_share,
        },
        "crn_check": crn,
        "summary_table": table,
        "comparisons": comparisons,
        "by_failure_class": by_cause,
        "detector": detector,
        "taxonomy": taxonomy,
        "models": models,
        "world_calibration": fit,
        "calibration_provenance": {
            "summary": cal.provenance_summary(),
            "table": cal.provenance_table(),
        },
    }
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nWrote {RESULTS_PATH}")

    print("\n" + "=" * 68)
    print(f"{'policy':14s} {'recovery':>9s} {'gmv':>8s} {'net INR':>12s} "
          f"{'cost INR':>9s} {'retries':>8s} {'nudges':>7s} {'waste':>6s}")
    for name, row in table.items():
        print(f"{name:14s} {row['recovery_rate']:9.2%} "
              f"{row['gmv_recovery_rate']:8.2%} "
              f"{row['net_value_paise'] / 100:12,.0f} "
              f"{row['total_cost_paise'] / 100:9,.0f} "
              f"{row['retries']:8.0f} {row['nudges']:7.0f} "
              f"{row['wasted_retries']:6.0f}")


if __name__ == "__main__":
    main()
