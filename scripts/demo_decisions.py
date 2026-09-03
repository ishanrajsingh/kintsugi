"""Print worked examples of the agent deciding, with its reasoning.

This is the demo surface: a merchant asking "why did you not chase my 40,000
rupee payment?" and getting an answer with numbers in it. Every decision the
agent takes is logged with the alternatives it considered and what each was
worth, so the answer is read out of the ledger rather than reconstructed.

Run: ``python -m scripts.demo_decisions [--seed N]``
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from kintsugi.agent.kintsugi import KintsugiPolicy
from kintsugi.agent.messaging import MessageWriter
from kintsugi.domain import Channel, FailureClass
from kintsugi.world.simulator import World, WorldConfig

RULE = "─" * 76


def inr(paise: float) -> str:
    return f"₹{paise / 100:,.0f}"


def clock(minute: int) -> str:
    day, rem = divmod(int(minute), 1440)
    return f"day {day + 1:2d}, {rem // 60:02d}:{rem % 60:02d}"


def show(decision: dict, payment, index: int) -> None:
    print(f"\n{RULE}")
    print(f"  [{index}]  {payment.payment_id}   {inr(payment.amount_paise)}   "
          f"{'recurring mandate' if payment.is_recurring else 'checkout'}")
    print(f"        failed: {decision['cause']}   at {clock(decision['at'])}")

    first = payment.attempts[0]
    if first.raw_error:
        print(f"        gateway said: \"{first.raw_error}\"")

    print(f"\n  DECISION: {decision['chosen']}"
          + (f" on {decision['rail']}" if decision.get("rail") else "")
          + (f" via {decision['channel']}" if decision.get("channel") else ""))
    print(f"  {decision['rationale']}")

    if decision.get("alternatives"):
        print("\n  priced alternatives:")
        for alt in decision["alternatives"][:5]:
            marker = "->" if _matches(alt["action"], decision) else "  "
            print(f"    {marker} {alt['action']:22s} "
                  f"P={alt['p']:6.1%}   worth {inr(alt['ev_paise']):>12s}")

    outcome = ("RECOVERED " + clock(payment.recovered_at)
               if payment.is_recovered else "written off")
    print(f"\n  outcome: {outcome}")


def _matches(action: str, decision: dict) -> bool:
    kind, _, detail = action.partition(":")
    if kind == "retry":
        return decision["chosen"] == "RETRY" and decision.get("rail") == detail
    if kind == "nudge":
        return decision["chosen"] == "NUDGE" and decision.get("channel") == detail
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=1000)
    parser.add_argument("--payments", type=int, default=6_000)
    args = parser.parse_args()

    world = World(WorldConfig(
        n_customers=2_000, n_payments=args.payments, seed=args.seed))
    agent = KintsugiPolicy()
    result = world.run(agent)
    by_id = {p.payment_id: p for p in result.payments}

    print(f"\n{RULE}")
    print("  KINTSUGI — worked decisions")
    print(f"  {len(result.payments):,} payments, seed {args.seed}, "
          f"{len(agent.decisions):,} logged decisions")
    print(RULE)

    # Pick one illustrative decision per cause, preferring large amounts --
    # those are the ones a merchant actually asks about.
    best: dict[str, tuple[int, dict]] = {}
    for decision in agent.decisions:
        cause = decision["cause"]
        amount = decision["amount_paise"]
        if cause not in best or amount > best[cause][0]:
            best[cause] = (amount, decision)

    order = [
        FailureClass.INSUFFICIENT_FUNDS, FailureClass.ISSUER_DOWN,
        FailureClass.AUTH_ABANDONED, FailureClass.RISK_DECLINE,
        FailureClass.LIMIT_EXCEEDED, FailureClass.AUTH_TIMEOUT,
    ]
    index = 0
    for cause in order:
        entry = best.get(cause.name)
        if not entry:
            continue
        index += 1
        show(entry[1], by_id[entry[1]["payment_id"]], index)

    # The signature behaviour: holding a balance failure for the salary credit
    # rather than burning attempts against an account that has no money in it.
    print(f"\n{RULE}")
    print("  HOLDING FOR PAYDAY — waiting priced against acting now")
    print(RULE)
    holds = [
        d for d in agent.decisions
        if d["chosen"] == "WAIT"
        and d["cause"] in ("INSUFFICIENT_FUNDS", "LIMIT_EXCEEDED")
        and "day" in d["rationale"]
    ]
    holds.sort(key=lambda d: -d["amount_paise"])
    for decision in holds[:4]:
        payment = by_id[decision["payment_id"]]
        print(f"\n  {inr(decision['amount_paise']):>12s}  "
              f"{decision['cause']:20s} failed {clock(decision['at'])}")
        print(f"    {decision['rationale']}")
        print(f"    -> {'RECOVERED ' + clock(payment.recovered_at)}"
              if payment.is_recovered else "    -> written off")
    if holds:
        recovered = sum(1 for d in holds if by_id[d['payment_id']].is_recovered)
        print(f"\n  {len(holds)} payments held for a better moment; "
              f"{recovered} ({recovered / len(holds):.0%}) recovered.")
        print("  A fixed +1d / +3d / +7d schedule reaches payday only by "
              "coincidence.")

    # Terminal causes never reach the ledger -- the taxonomy settles them
    # before the model is consulted. Show that explicitly, because "the agent
    # refused to even ask" is the point.
    print(f"\n{RULE}")
    print("  TERMINAL CAUSES — settled before any model is consulted")
    print(RULE)
    terminal = defaultdict(list)
    for payment in result.payments:
        if not payment.attempts or payment.attempts[0].succeeded:
            continue
        cause = payment.attempts[0].failure_class
        if cause and cause.is_terminal:
            terminal[cause.name].append(payment)
    for name, payments in sorted(terminal.items()):
        total = sum(p.amount_paise for p in payments)
        retries = sum(p.retry_count for p in payments)
        print(f"  {name:22s} {len(payments):4d} payments   {inr(total):>13s} "
              f"written off   {retries} retries spent")
    print("\n  A dead instrument cannot be revived. Every retry against one is "
          "pure cost:\n  gateway load, issuer trust, and a customer watching "
          "their payment fail again.")

    # -- the copy that would actually be sent --------------------------------
    print(f"\n{RULE}")
    print("  CUSTOMER COPY — generated per cause, validated before sending")
    print(RULE)
    writer = MessageWriter()
    for cause in (FailureClass.INSUFFICIENT_FUNDS, FailureClass.AUTH_ABANDONED,
                  FailureClass.ISSUER_DOWN, FailureClass.CARD_BLOCKED):
        message = writer.write(cause, Channel.SMS, 125_000, merchant="Acme")
        print(f"\n  {cause.name}  [{message.source}, {len(message.text)} chars]")
        print(f"    \"{message.text}\"")
    print("\n  Note how different these are. 'Your payment failed, please try "
          "again'\n  is wrong for every one of them.")
    print()


if __name__ == "__main__":
    main()
