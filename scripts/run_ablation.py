"""Decompose the lift: which idea actually earns the money?

A single headline number tells you the agent is better without telling you
*why*, and "why" is the part that transfers. If nearly all the gain comes from
one component, the other three are complexity to be deleted rather than
features to be proud of.

Each variant removes exactly one idea and keeps the rest:

``full``            everything on
``no_wait_search``  waiting is no longer evaluated against future moments; the
                    agent acts greedily whenever an action clears its cost.
                    This is the ablation that matters most -- it tests the
                    central claim that *when* to act is worth more than *what*
                    to do.
``no_payday``       the salary-credit date is dropped from the candidate
                    moments. The agent can still wait, but only on a geometric
                    grid, so it can reach payday only by accident.
``no_monitor``      retry probabilities are no longer scaled by inferred issuer
                    health. Isolates what the outage detector is worth.
``no_model``        both predictors are replaced by their base rates, so every
                    payment gets the same probability. Isolates how much comes
                    from the expected-value framing alone -- amount-awareness,
                    cost accounting and terminal-cause handling -- with no
                    learning at all.

Run: ``python -m scripts.run_ablation [--seeds N] [--payments N]``
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from kintsugi.agent.kintsugi import AgentConfig, KintsugiPolicy
from kintsugi.agent.policy import RuleBasedPolicy
from kintsugi.agent.predictor import Predictor
from kintsugi.eval.harness import compare, evaluate
from kintsugi.world.simulator import WorldConfig

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "ablation.json"


class ConstantModel:
    """Returns the training base rate for everything. No signal, calibrated."""

    def __init__(self, p: float) -> None:
        self.p = p

    def predict(self, x) -> float:
        return self.p

    def predict_batch(self, X) -> np.ndarray:
        return np.full(len(X), self.p)


def variants() -> dict[str, callable]:
    retry = Predictor.load("retry")
    nudge = Predictor.load("nudge")

    def full():
        p = KintsugiPolicy(); p.name = "full"; return p

    def no_wait_search():
        p = KintsugiPolicy(config=AgentConfig(
            candidate_offsets=(), consider_payday=False))
        p.name = "no_wait_search"
        return p

    def no_payday():
        p = KintsugiPolicy(config=AgentConfig(consider_payday=False))
        p.name = "no_payday"
        return p

    def no_monitor():
        p = KintsugiPolicy(config=AgentConfig(use_monitor=False))
        p.name = "no_monitor"
        return p

    def no_model():
        p = KintsugiPolicy(
            retry_model=ConstantModel(retry.fallback_rate),
            nudge_model=ConstantModel(nudge.fallback_rate))
        p.name = "no_model"
        return p

    return {
        "full": full, "no_wait_search": no_wait_search,
        "no_payday": no_payday, "no_monitor": no_monitor,
        "no_model": no_model,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--payments", type=int, default=8_000)
    parser.add_argument("--customers", type=int, default=2_500)
    args = parser.parse_args()

    config = WorldConfig(n_customers=args.customers, n_payments=args.payments)
    factories = variants()

    print(f"Ablation: {args.seeds} seeds x {args.payments:,} payments")
    print("Each variant removes one idea; rule_based is the reference.")
    print("=" * 74)

    def policies():
        return [RuleBasedPolicy()] + [f() for f in factories.values()]

    t0 = time.time()
    results = evaluate(policies(), config, n_seeds=args.seeds, progress=True)

    rows = []
    full_lift = None
    for name in factories:
        c = compare(results, "rule_based", name, "net_value_paise")
        rec = compare(results, "rule_based", name, "recovery_rate")
        if name == "full":
            full_lift = c.relative_lift
        rows.append({
            "variant": name,
            "net_lift_vs_rules": c.relative_lift,
            "recovery_lift_vs_rules": rec.relative_lift,
            "ci_low": c.ci_low, "ci_high": c.ci_high,
            "significant": c.significant,
            "win_rate": c.win_rate,
            "p_value": c.p_value,
        })

    # How much of the full agent's advantage each idea is responsible for.
    for row in rows:
        if row["variant"] == "full" or not full_lift:
            row["share_of_lift"] = None
        else:
            row["share_of_lift"] = (full_lift - row["net_lift_vs_rules"]) / full_lift

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "config": {"seeds": args.seeds, "payments": args.payments},
        "rows": rows,
    }, indent=2))

    print("\n" + "=" * 74)
    print(f"{'variant':16s} {'net lift':>10s} {'recovery lift':>14s} "
          f"{'wins':>6s} {'sig':>5s} {'share of full lift':>19s}")
    for row in rows:
        share = ("—" if row["share_of_lift"] is None
                 else f"{row['share_of_lift']:.0%}")
        print(f"{row['variant']:16s} {row['net_lift_vs_rules']:+10.2%} "
              f"{row['recovery_lift_vs_rules']:+14.2%} "
              f"{row['win_rate']:6.0%} "
              f"{'yes' if row['significant'] else 'no':>5s} {share:>19s}")
    print("\n'share of full lift' = how much of the agent's advantage "
          "disappears\nwhen that one idea is removed.")
    print(f"\nWrote {OUT_PATH}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
