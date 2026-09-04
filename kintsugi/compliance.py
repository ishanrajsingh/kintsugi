"""Scheme and regulator limits on retrying.

These aren't costs to weigh against a benefit -- they're limits you don't get
to weigh, enforced by the network rather than your own accounting. So this sits
*above* the expected-value engine and filters the action set before anything is
priced. No probability estimate buys its way past it.

The rules we enforce:

- UPI Autopay (NPCI, from 1 Aug 2025): one debit attempt plus at most three
  retries per mandate, executable only in the non-peak windows -- before 10:00,
  13:00-17:00, after 21:30.
- Cards: Visa caps card-not-present resubmissions at 15 per card per merchant
  per rolling 30 days, with an excessive-reattempt fee past that. Mastercard's
  Transaction Processing Excellence programme is a *dual* threshold instead --
  10 attempts in 24 hours and 35 in 30 days -- plus a per-transaction penalty
  for retrying after Merchant Advice Code 03 (fraud) or 21 (lost/stolen).
- Both schemes prohibit reattempting a "never retry" decline outright.

We enforce Visa's 15-per-30-days, which is the strictest of the three numeric
limits and so satisfies all of them. Mastercard's 24-hour threshold is the one
that could in principle bind independently; measured across all three policies
it does not come close (worst case 6 attempts on a card in any 24 hours against
a limit of 10), so a separate check would add machinery and catch nothing.

Secondary sources disagree on whether Visa's figure is 15 or 20. Enforcing 15
is safe under either reading.

A fixed schedule has no idea any of this exists -- it'll fire a mandate retry at
11:00 or make a fifth attempt on a card the issuer told it to stop using. Those
are the violations counted here, and they're a real cost that a headline
recovery rate hides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from kintsugi.domain import Minute, Payment, Rail

MINUTES_PER_DAY = 1440


class Scheme(Enum):
    """Which rule set governs a given payment."""

    UPI_AUTOPAY = auto()
    """NPCI recurring mandate rules."""

    CARD = auto()
    """Card network resubmission rules."""

    OPEN = auto()
    """Customer-initiated UPI and netbanking: no scheme retry cap applies,
    though the merchant's own budget still does."""


def scheme_for(payment: Payment) -> Scheme:
    if payment.is_recurring and payment.preferred_rail in (
            Rail.UPI_INTENT, Rail.UPI_COLLECT):
        return Scheme.UPI_AUTOPAY
    if payment.preferred_rail is Rail.CARD:
        return Scheme.CARD
    return Scheme.OPEN


# ---------------------------------------------------------------------------
# NPCI UPI Autopay execution windows
# ---------------------------------------------------------------------------

#: Permitted execution windows for recurring UPI mandates, as (start, end) in
#: hours. Outside these, a mandate debit must not be attempted.
AUTOPAY_WINDOWS: tuple[tuple[float, float], ...] = (
    (0.0, 10.0),     # before 10:00
    (13.0, 17.0),    # 13:00 - 17:00
    (21.5, 24.0),    # after 21:30
)

#: One main attempt plus at most three retries, per NPCI.
AUTOPAY_MAX_RETRIES = 3

#: Visa: 15 resubmissions per card per rolling 30 days for retryable declines.
CARD_MAX_ATTEMPTS_PER_WINDOW = 15
CARD_WINDOW_MINUTES = 30 * MINUTES_PER_DAY


def in_autopay_window(at: Minute) -> bool:
    hour = (at % MINUTES_PER_DAY) / 60.0
    return any(start <= hour < end for start, end in AUTOPAY_WINDOWS)


def next_autopay_window(at: Minute) -> Minute:
    """The earliest permitted execution time at or after ``at``.

    Used by the agent to *move* a mandate retry into a legal window rather
    than abandoning it, which is what the rule is for: NPCI is spreading load
    off the peak, not forbidding the collection.
    """
    if in_autopay_window(at):
        return at
    day_start = (at // MINUTES_PER_DAY) * MINUTES_PER_DAY
    hour = (at % MINUTES_PER_DAY) / 60.0
    for start, _ in AUTOPAY_WINDOWS:
        if hour < start:
            return day_start + int(start * 60)
    # Past the last window's start but not inside it: go to tomorrow's first.
    return day_start + MINUTES_PER_DAY


@dataclass(frozen=True, slots=True)
class Verdict:
    allowed: bool
    rule: str = ""
    fine_paise: int = 0

    @property
    def violated(self) -> bool:
        return not self.allowed


ALLOWED = Verdict(True)


class RuleBook:
    """Checks a proposed retry against scheme and regulator rules.

    Stateless with respect to the policy: it reads only the payment's own
    attempt history plus a per-instrument attempt counter, both of which a real
    merchant has.
    """

    def __init__(
        self,
        excessive_card_fee_paise: int = 2_100,
        autopay_breach_fee_paise: int = 5_000,
    ) -> None:
        self.excessive_card_fee_paise = excessive_card_fee_paise
        """Visa excessive-reattempt fee, ~USD 0.25 converted."""

        self.autopay_breach_fee_paise = autopay_breach_fee_paise
        """NPCI does not publish a per-breach figure; this is a stand-in so a
        non-compliant policy carries *some* modelled cost rather than none.
        Swept in the sensitivity analysis like any other assumption."""

        self.violations: list[dict] = []

    def reset(self) -> None:
        self.violations.clear()

    def check_retry(
        self, payment: Payment, at: Minute, attempts_on_instrument: int = 0
    ) -> Verdict:
        """May this retry be made, at this instant?"""
        last = payment.last_attempt

        # --- never retry a decline the scheme classes as terminal ---------
        if last is not None and last.failure_class is not None \
                and last.failure_class.is_terminal:
            return Verdict(
                False,
                f"scheme prohibits reattempting {last.failure_class.name}",
                self.excessive_card_fee_paise,
            )

        scheme = scheme_for(payment)

        if scheme is Scheme.UPI_AUTOPAY:
            if payment.retry_count >= AUTOPAY_MAX_RETRIES:
                return Verdict(
                    False,
                    f"NPCI: mandate limited to {AUTOPAY_MAX_RETRIES} retries",
                    self.autopay_breach_fee_paise,
                )
            if not in_autopay_window(at):
                hour = (at % MINUTES_PER_DAY) / 60.0
                return Verdict(
                    False,
                    f"NPCI: autopay outside permitted window ({hour:04.1f}h)",
                    self.autopay_breach_fee_paise,
                )

        elif scheme is Scheme.CARD:
            if attempts_on_instrument >= CARD_MAX_ATTEMPTS_PER_WINDOW:
                return Verdict(
                    False,
                    f"Visa: over {CARD_MAX_ATTEMPTS_PER_WINDOW} resubmissions "
                    f"in 30 days",
                    self.excessive_card_fee_paise,
                )

        return ALLOWED

    def record(self, payment: Payment, at: Minute, verdict: Verdict) -> None:
        self.violations.append({
            "payment_id": payment.payment_id,
            "at": at,
            "rule": verdict.rule,
            "fine_paise": verdict.fine_paise,
        })

    @property
    def total_fines_paise(self) -> int:
        return sum(v["fine_paise"] for v in self.violations)

    def summary(self) -> dict:
        by_rule: dict[str, int] = {}
        for v in self.violations:
            key = v["rule"].split(":")[0] if ":" in v["rule"] else v["rule"]
            by_rule[key] = by_rule.get(key, 0) + 1
        return {
            "violations": len(self.violations),
            "fines_paise": self.total_fines_paise,
            "by_rule": by_rule,
        }


def constrain(action, payment: Payment, now: Minute, rulebook: RuleBook,
              attempts_on_instrument: int = 0):
    """Rewrite a proposed action into a compliant one, or stop.

    Deliberately shared by every serious policy rather than built into the
    learned agent, because these rules are not a competitive advantage --
    they are mandatory, and any team shipping recovery logic implements them.
    Giving the agent private access to them would manufacture a lead that has
    nothing to do with whether its decisions are good.

    A blocked retry becomes a *wait until the rule permits it* wherever the rule
    is about timing, because NPCI's windows exist to move load off the peak,
    not to forbid the collection. Only a hard cap or a scheme-prohibited
    reattempt turns into a stop.
    """
    from kintsugi.domain import Action, ActionKind

    if action.kind is not ActionKind.RETRY:
        return action

    verdict = rulebook.check_retry(payment, now, attempts_on_instrument)
    if verdict.allowed:
        return action

    if "window" in verdict.rule:
        target = next_autopay_window(now)
        return Action.wait(
            max(1, target - now),
            f"{verdict.rule}; holding until the next permitted window",
        )
    return Action.abandon(verdict.rule)
