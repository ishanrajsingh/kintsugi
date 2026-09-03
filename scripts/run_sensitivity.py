"""Sweep the assumptions and report where the result holds and where it breaks.

The fair objection to this project is that the world is ours, so the lift could
be an artefact of a number we picked. This script answers it by moving every
constant that carries ``Provenance.ASSUMPTION`` -- the ones with no published
source -- well above and below its default, including to settings deliberately
hostile to the agent, and re-running the whole paired comparison at each.

Regressions are reported as loudly as improvements. A lift that exists only at
one setting of an assumed constant is not a result, and this is the script that
would say so.

Run: ``python -m scripts.run_sensitivity [--seeds N] [--payments N]``
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.agent.policy import FixedRetryPolicy, RuleBasedPolicy
from kintsugi.eval.sensitivity import run_sweep, summarise
from kintsugi.world.simulator import WorldConfig

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "sensitivity.json"


def policies() -> list:
    return [FixedRetryPolicy(), RuleBasedPolicy(), KintsugiPolicy()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--payments", type=int, default=6_000)
    parser.add_argument("--customers", type=int, default=2_000)
    parser.add_argument("--metric", default="net_value_paise")
    parser.add_argument("--baseline", default="rule_based")
    args = parser.parse_args()

    config = WorldConfig(n_customers=args.customers, n_payments=args.payments)

    print(f"Sensitivity sweep: {args.seeds} seeds x {args.payments:,} payments")
    print(f"kintsugi vs {args.baseline} on {args.metric}")
    print("=" * 68)

    t0 = time.time()
    results = run_sweep(
        policies, config, baseline=args.baseline, challenger="kintsugi",
        metric=args.metric, n_seeds=args.seeds)
    summary = summarise(results)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "config": {
            "seeds": args.seeds, "payments": args.payments,
            "baseline": args.baseline, "metric": args.metric,
        },
        "summary": summary,
        "results": [r.to_dict() for r in results],
    }, indent=2))

    print("\n" + "=" * 68)
    print(f"perturbations swept      {summary['n_perturbations']}")
    print(f"lift positive in         {summary['positive']}")
    print(f"significantly positive   {summary['significant_positive']}")
    print(f"significantly NEGATIVE   {summary['significant_negative']}")
    print(f"lift range               {summary['min_lift']:+.2%} to "
          f"{summary['max_lift']:+.2%}  (median {summary['median_lift']:+.2%})")
    if summary["regressions"]:
        print(f"\nREGRESSIONS -- the agent loses under these assumptions:")
        for label in summary["regressions"]:
            print(f"  - {label}")
    else:
        print("\nNo setting of any assumed constant reversed the result.")
    print(f"\nWrote {OUT_PATH}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
