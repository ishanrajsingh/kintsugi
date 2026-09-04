"""How much of the recoverable money does the agent actually get?

Beating a baseline says nothing about how much is left behind. The simulator
resolves an attempt as a deterministic function of (payment, rail, time,
attempt_no), so a policy allowed to probe it directly can *find* the best
moment instead of predicting it. That is not deployable -- it reads latent
state -- but it bounds what any retry policy could achieve, and the gap is the
headroom better prediction could in principle capture.

Two details decide whether the number means anything.

The oracle does not make failing attempts. It inspects freely and commits
once, so ``attempt_no`` stays at the first retry throughout. An earlier version
advanced the counter on every probe, spent a six-attempt budget inspecting one
or two moments, and produced a "ceiling" below the agent -- which is how that
bug announced itself.

And this bounds retries only. A nudge can also recover a payment by reviving a
dead instrument, so it is the ceiling for the lever the agent mostly pulls,
not for the agent overall.

Run: ``python -m scripts.run_oracle_ceiling``
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from statistics import mean

from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.agent.policy import FixedRetryPolicy, RuleBasedPolicy
from kintsugi.domain import Rail
from kintsugi.eval import metrics as M
from kintsugi.world.simulator import World, WorldConfig

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "oracle_ceiling.json"
SEEDS = [1000, 1007, 1014]
HOUR, DAY = 60, 1440
PROBE_GRID = list(range(HOUR, 14 * DAY, 3 * HOUR))
BUCKETS = [(0, 50_000), (50_000, 150_000), (150_000, 400_000),
           (400_000, 1_000_000), (1_000_000, 10 ** 12)]


def _label(lo: int, hi: int) -> str:
    return f"INR {lo // 100:,}-{hi // 100:,}" if hi < 10 ** 12 else f"INR {lo // 100:,}+"


def ceiling(world: World) -> tuple[float, float, dict]:
    """Share of first-attempt failures some legal retry could have recovered."""
    rec = fail = gmv_rec = gmv_tot = 0
    buckets = {b: {"n": 0, "hit": 0, "gmv": 0, "hit_gmv": 0} for b in BUCKETS}

    for p in world._template:
        ok, _ = world.resolve_attempt(p, p.preferred_rail, p.created_at, 0)
        if ok:
            continue
        fail += 1
        gmv_tot += p.amount_paise
        b = buckets[next(x for x in BUCKETS if x[0] <= p.amount_paise < x[1])]
        b["n"] += 1
        b["gmv"] += p.amount_paise

        hit = any(
            world.resolve_attempt(p, rail, p.created_at + off, 1)[0]
            for off in PROBE_GRID for rail in Rail
        )
        if hit:
            rec += 1
            gmv_rec += p.amount_paise
            b["hit"] += 1
            b["hit_gmv"] += p.amount_paise

    return rec / fail, gmv_rec / gmv_tot, {
        _label(*k): {"failed": v["n"],
                     "oracle_recovery": v["hit"] / v["n"] if v["n"] else 0.0,
                     "gmv_paise": v["gmv"]}
        for k, v in buckets.items()
    }


def main() -> None:
    config = WorldConfig(n_customers=3_000, n_payments=12_000)

    print("What share of recoverable money does each policy get?")
    print("=" * 66)
    rows = {}
    for name, factory in (("fixed_retry", FixedRetryPolicy),
                          ("rule_based", RuleBasedPolicy),
                          ("kintsugi", KintsugiPolicy)):
        ms = [M.compute(World(replace(config, seed=s)).run(factory())) for s in SEEDS]
        rows[name] = {
            "recovery_rate": mean(m.recovery_rate for m in ms),
            "gmv_recovery_rate": mean(m.gmv_recovery_rate for m in ms),
        }
        print(f"  {name:28s} {rows[name]['recovery_rate']:7.2%} recovery  "
              f"{rows[name]['gmv_recovery_rate']:7.2%} value")

    rs, gs, bs = zip(*(ceiling(World(replace(config, seed=s))) for s in SEEDS))
    oracle = {"recovery_rate": mean(rs), "gmv_recovery_rate": mean(gs)}
    print(f"  {'ORACLE (retry-only ceiling)':28s} {oracle['recovery_rate']:7.2%} recovery  "
          f"{oracle['gmv_recovery_rate']:7.2%} value")

    print()
    for name, r in rows.items():
        print(f"  {name:28s} captures {r['recovery_rate'] / oracle['recovery_rate']:6.1%} of "
              f"recoverable payments, {r['gmv_recovery_rate'] / oracle['gmv_recovery_rate']:6.1%} of value")

    print("\n  Oracle recovery by amount (where the headroom is):")
    for label, v in bs[0].items():
        print(f"    {label:22s} {v['failed']:5,} failed   "
              f"oracle {v['oracle_recovery']:6.1%}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "seeds": SEEDS, "policies": rows, "oracle": oracle,
        "oracle_by_amount": bs[0],
        "capture": {k: {"payments": v["recovery_rate"] / oracle["recovery_rate"],
                        "value": v["gmv_recovery_rate"] / oracle["gmv_recovery_rate"]}
                    for k, v in rows.items()},
    }, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
