"""Trade customer contact against recovery, and find where the trade turns.

An expected-value agent given only the *send* price of a message will message
everyone forever: 20 paise against a payment worth hundreds of rupees clears
almost any bar. What that arithmetic misses is that attention is not free to
the business either -- unsubscribes, uninstalls, reputation, and the erosion of
every future message's effectiveness. None of it appears on the telecom
invoice, so none of it enters the decision unless it is priced deliberately.

This sweeps that price and reports the frontier. The interesting question is
not "how much recovery does restraint cost" but whether it costs any at all:
if over-contacting is genuinely destructive rather than merely wasteful, then
pricing it correctly should make the agent *cheaper and better at the same
time*, and the frontier will have an interior optimum rather than a
monotone trade-off.

Run: ``python -m scripts.run_contact_frontier``
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from kintsugi.agent.kintsugi import AgentConfig, KintsugiPolicy
from kintsugi.agent.policy import FixedRetryPolicy, RuleBasedPolicy
from kintsugi.eval.harness import evaluate, summary_table
from kintsugi.world.simulator import WorldConfig

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "contact_frontier.json"

#: Goodwill charged per customer contact, in paise, beyond the send price.
PRICES = (0, 500, 1_500, 5_000, 15_000, 50_000)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=8)
    parser.add_argument("--payments", type=int, default=6_000)
    parser.add_argument("--customers", type=int, default=2_000)
    args = parser.parse_args()

    config = WorldConfig(n_customers=args.customers, n_payments=args.payments)

    def policies():
        out = [FixedRetryPolicy(), RuleBasedPolicy()]
        for price in PRICES:
            policy = KintsugiPolicy(
                config=AgentConfig(contact_goodwill_price_paise=price))
            policy.name = f"kintsugi_g{price}"
            out.append(policy)
        return out

    print(f"Contact frontier: {args.seeds} seeds x {args.payments:,} payments")
    print("=" * 76)
    results = evaluate(policies(), config, n_seeds=args.seeds, progress=True)
    table = summary_table(results)

    print(f"\n{'policy':>22s} {'recovery':>9s} {'gmv':>8s} {'nudges':>8s} "
          f"{'retries':>8s} {'cost INR':>9s} {'churn':>6s}")
    rows = []
    for name, row in table.items():
        label = name
        if name.startswith("kintsugi_g"):
            label = f"kintsugi @ INR {int(name[10:]) / 100:.0f}/contact"
        print(f"{label:>22s} {row['recovery_rate']:9.2%} "
              f"{row['gmv_recovery_rate']:8.2%} {row['nudges']:8.0f} "
              f"{row['retries']:8.0f} {row['total_cost_paise'] / 100:9,.0f} "
              f"{row['churned']:6.1f}")
        rows.append({"policy": name, "label": label, **row})

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "config": {"seeds": args.seeds, "payments": args.payments},
        "prices_paise": list(PRICES),
        "rows": rows,
    }, indent=2))

    agent_rows = [r for r in rows if r["policy"].startswith("kintsugi_g")]
    best = max(agent_rows, key=lambda r: r["gmv_recovery_rate"])
    cheapest_beating_rules = None
    rules = table.get("rule_based")
    if rules:
        candidates = [r for r in agent_rows
                      if r["gmv_recovery_rate"] > rules["gmv_recovery_rate"]]
        if candidates:
            cheapest_beating_rules = min(candidates, key=lambda r: r["nudges"])

    print("\n" + "=" * 76)
    print(f"best value recovered : {best['label']} at "
          f"{best['gmv_recovery_rate']:.2%} with {best['nudges']:.0f} messages")
    if cheapest_beating_rules:
        print(f"quietest that still beats the rules baseline: "
              f"{cheapest_beating_rules['label']}")
        print(f"  {cheapest_beating_rules['gmv_recovery_rate']:.2%} value "
              f"recovered on {cheapest_beating_rules['nudges']:.0f} messages, "
              f"against the baseline's {rules['nudges']:.0f}")
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
