"""What does obeying the rules cost?

Compliance is not optional, so this is not a trade-off anyone gets to make. It
is still worth measuring, for two reasons: a recovery figure quoted without it
is not comparable to one quoted with it, and a reader is entitled to know how
much of the gap between this agent and a naive schedule is the naive schedule
simply breaking rules.

Method: run the agent twice against identical worlds, once normally and once
with its rulebook neutered, and difference the results. The neutered variant
exists only here -- it is not a configuration the shipped agent can be put
into, because "ignore NPCI" is not a setting a payments system should expose.

Run: ``python -m scripts.run_compliance_cost``
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from statistics import mean

from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.compliance import ALLOWED
from kintsugi.eval import metrics as M
from kintsugi.world.simulator import World, WorldConfig

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "compliance_cost.json"
SEEDS = [1000, 1007, 1014, 1021, 1028]


class _Unconstrained(KintsugiPolicy):
    """The same agent with every scheme check answering 'allowed'."""

    name = "kintsugi_ignoring_the_rules"

    def __init__(self) -> None:
        super().__init__()
        self.rulebook.check_retry = lambda *a, **k: ALLOWED


def main() -> None:
    config = WorldConfig(n_customers=2_000, n_payments=8_000)
    worlds = [World(replace(config, seed=s)) for s in SEEDS]

    rows = {}
    for label, factory in (("compliant", KintsugiPolicy),
                           ("ignoring the rules", _Unconstrained)):
        metrics = [M.compute(w.run(factory())) for w in worlds]
        rows[label] = {
            "recovery_rate": mean(m.recovery_rate for m in metrics),
            "gmv_recovery_rate": mean(m.gmv_recovery_rate for m in metrics),
            "scheme_violations": mean(m.scheme_violations for m in metrics),
            "fines_paise": mean(m.fines_paise for m in metrics),
        }

    a, b = rows["compliant"], rows["ignoring the rules"]
    summary = {
        "recovery_cost_pp": (b["recovery_rate"] - a["recovery_rate"]) * 100,
        "value_cost_pp": (b["gmv_recovery_rate"] - a["gmv_recovery_rate"]) * 100,
        "violations_avoided": b["scheme_violations"],
        "fines_avoided_paise": b["fines_paise"],
    }

    print("What obeying NPCI and the card schemes costs this agent")
    print("=" * 66)
    for label, r in rows.items():
        print(f"  {label:20s} recovery {r['recovery_rate']:.2%}  "
              f"value {r['gmv_recovery_rate']:.2%}  "
              f"violations {r['scheme_violations']:.0f}  "
              f"fines INR {r['fines_paise'] / 100:,.0f}")
    print()
    print(f"  cost of compliance : {summary['recovery_cost_pp']:.2f}pp recovery, "
          f"{summary['value_cost_pp']:.2f}pp of value")
    print(f"  avoided            : {summary['violations_avoided']:.0f} violations, "
          f"INR {summary['fines_avoided_paise'] / 100:,.0f} in fines")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(
        {"seeds": SEEDS, "rows": rows, "summary": summary}, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
