"""Does the agent starve its own outage detector?

An oddity worth chasing: the health monitor scored 96% precision when a
rules policy was driving traffic, and 81% when the Kintsugi agent was. The
detector code is identical in both cases, so something about *who is making the
attempts* is changing what it can see.

Two candidate explanations, and they have different consequences:

**Volume.** The two measurements ran at different payment counts. A brief
outage on a low-volume issuer produces almost no attempts to observe, so recall
falls with traffic for reasons that have nothing to do with the policy.

**Closed-loop starvation.** The agent *uses* the detector: when it believes an
issuer is impaired it stops retrying there. That removes exactly the attempts
that would have confirmed the outage. A detector wired into the policy it
informs is measuring a world its own output has altered -- and this is a real
production effect, not a simulation artefact. Any system that routes away from
a suspected-bad endpoint stops receiving evidence about that endpoint.

This script separates them by measuring the same detector, at the same volumes,
under a policy that consumes its output and one that ignores it.

Run: ``python -m scripts.run_detector_study``
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from statistics import mean

from kintsugi.agent.health_monitor import IssuerHealthMonitor, score_detection
from kintsugi.agent.kintsugi import AgentConfig, KintsugiPolicy
from kintsugi.agent.policy import RuleBasedPolicy
from kintsugi.world.simulator import World, WorldConfig

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "detector_study.json"
SEEDS = [101, 102, 103, 104, 105]


class ObservingRules(RuleBasedPolicy):
    """Rules policy carrying a monitor it never consults.

    The open-loop control: the detector sees the traffic but has no influence
    over it, so its measurement is uncontaminated by its own output.
    """

    name = "rules_open_loop"

    def __init__(self) -> None:
        self.monitor = IssuerHealthMonitor()

    def reset(self) -> None:
        self.monitor.reset()

    def observe(self, payment, attempt, now) -> None:
        self.monitor.observe(
            payment.issuer, now, attempt.succeeded, attempt.failure_class)


def measure(policy_factory, config: WorldConfig) -> dict:
    precision, recall, latency = [], [], []
    strata: dict[str, list[int]] = {}

    for seed in SEEDS:
        world = World(replace(config, seed=seed))
        policy = policy_factory()
        world.run(policy)
        score = score_detection(policy.monitor, world.issuers)
        precision.append(score.precision)
        recall.append(score.recall)
        if score.latencies:
            latency.append(score.median_latency)
        for label, row in score.by_duration.items():
            bucket = strata.setdefault(label, [0, 0])
            bucket[0] += row["detected"]
            bucket[1] += row["incidents"]

    return {
        "precision": mean(precision),
        "recall": mean(recall),
        "median_latency_min": mean(latency) if latency else float("nan"),
        "recall_by_duration": {
            k: {"detected": v[0], "incidents": v[1],
                "recall": v[0] / v[1] if v[1] else float("nan")}
            for k, v in sorted(strata.items())
        },
    }


def main() -> None:
    rows = []
    print("Detector under open loop (ignores its own output) vs closed loop")
    print("=" * 72)
    print(f"{'volume':>9s}  {'policy':<18s} {'precision':>10s} {'recall':>8s} "
          f"{'latency':>8s}")

    for payments in (20_000, 60_000):
        config = WorldConfig(n_customers=4_000, n_payments=payments)
        for label, factory in (
            ("open loop (rules)", ObservingRules),
            ("closed loop (agent)", lambda: KintsugiPolicy()),
            ("agent, monitor off", lambda: KintsugiPolicy(
                config=AgentConfig(use_monitor=False))),
        ):
            stats = measure(factory, config)
            rows.append({"payments": payments, "policy": label, **stats})
            print(f"{payments:9,d}  {label:<18s} {stats['precision']:10.1%} "
                  f"{stats['recall']:8.1%} "
                  f"{stats['median_latency_min']:7.0f}m")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({"seeds": SEEDS, "rows": rows}, indent=2))

    # Same volume, different policies -> the closed-loop effect.
    hi = {r["policy"]: r for r in rows if r["payments"] == 60_000}
    print("\n" + "=" * 72)
    print("At matched volume (60,000 payments):")
    open_loop = hi["open loop (rules)"]
    closed = hi["closed loop (agent)"]
    off = hi["agent, monitor off"]
    print(f"  detector ignored by the policy : precision "
          f"{open_loop['precision']:.1%}, recall {open_loop['recall']:.1%}")
    print(f"  detector used by the policy    : precision "
          f"{closed['precision']:.1%}, recall {closed['recall']:.1%}")
    print(f"  agent running, monitor ignored : precision "
          f"{off['precision']:.1%}, recall {off['recall']:.1%}")
    print("\nThe gap between the last two isolates the closed-loop effect: same")
    print("agent, same traffic pattern, differing only in whether it acts on the")
    print("detector's output and so stops generating the evidence that would")
    print("confirm the outage.")
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
