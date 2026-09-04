"""Train the recovery predictors on exploration data.

Training worlds come from a seed band the evaluation never touches::

    train      2000-2029     here
    detector   11-13         health-monitor threshold sweep
    evaluate   1000-1203     kintsugi.eval.harness default

Nothing reported is fitted on the worlds it's reported on. That matters more
than usual here because the simulator is ours -- train on the evaluation seeds
and the model learns that world's realised outages and salary draws, so the
"lift" is partly memorisation of the test set dressed up as intelligence.

Data comes from the randomised explorers, never a sensible policy, for the
coverage reason in kintsugi.agent.explorer.

Run: ``python -m scripts.train_predictor``
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from kintsugi.agent.explorer import ExplorationPolicy, ScheduledExplorationPolicy
from kintsugi.agent.features import build_nudge_dataset, build_retry_dataset
from kintsugi.agent.health_monitor import IssuerHealthMonitor
from kintsugi.agent.predictor import Predictor
from kintsugi.world.simulator import World, WorldConfig

TRAIN_SEEDS = list(range(2000, 2030))
REPORT_PATH = Path(__file__).resolve().parents[1] / "data" / "model_report.json"


def collect(seeds, n_payments: int = 20_000, n_customers: int = 4_000):
    """Run the explorers across many worlds and stack the resulting rows."""
    Xr, yr, Xn, yn = [], [], [], []
    base = WorldConfig(n_customers=n_customers, n_payments=n_payments)

    for i, seed in enumerate(seeds):
        world = World(replace(base, seed=seed))
        for policy in (ExplorationPolicy(seed=9000 + seed),
                       ScheduledExplorationPolicy(seed=9500 + seed)):
            result = world.run(policy)
            a, b, _ = build_retry_dataset(result, IssuerHealthMonitor())
            c, d, _ = build_nudge_dataset(result, IssuerHealthMonitor())
            if len(a):
                Xr.append(a); yr.append(b)
            if len(c):
                Xn.append(c); yn.append(d)
        if (i + 1) % 10 == 0:
            print(f"    {i + 1}/{len(seeds)} training worlds")

    return (
        np.concatenate(Xr), np.concatenate(yr),
        np.concatenate(Xn), np.concatenate(yn),
    )


def main() -> None:
    print(f"Collecting exploration data from {len(TRAIN_SEEDS)} worlds "
          f"(seeds {TRAIN_SEEDS[0]}-{TRAIN_SEEDS[-1]})...")
    Xr, yr, Xn, yn = collect(TRAIN_SEEDS)
    print(f"\n  retry rows: {len(Xr):,}  positives {yr.mean():.3%}")
    print(f"  nudge rows: {len(Xn):,}  positives {yn.mean():.3%}")

    reports = {}
    for name, X, y in (("retry", Xr, yr), ("nudge", Xn, yn)):
        print(f"\nFitting {name} predictor...")
        p = Predictor(name)
        report = p.fit(X, y)
        path = p.save()
        reports[name] = report.to_dict()
        print(f"  AUC   {report.auc:.4f}")
        print(f"  Brier {report.brier:.5f}  (base rate {report.brier_baseline:.5f})")
        print(f"  Brier skill score {report.brier_skill_score:+.4f}")
        print(f"  Expected calibration error {report.expected_calibration_error:.4f}")
        print(f"  saved -> {path}")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps({
        "train_seeds": [TRAIN_SEEDS[0], TRAIN_SEEDS[-1]],
        "models": reports,
    }, indent=2))
    print(f"\nWrote {REPORT_PATH}")


if __name__ == "__main__":
    main()
