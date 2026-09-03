"""Recovery policies, including the baselines the agent must beat.

A word on the baselines
-----------------------
It is easy to manufacture a large improvement by comparing against a bad
baseline. The comparison that matters is against what a competent payments
team actually ships, so :class:`RuleBasedPolicy` below is written to be good:
it reads the failure cause, abandons terminal instruments immediately, waits
out issuer incidents, times balance retries against the salary cycle, and
nudges rather than hammers when the customer is the blocker. That is a real
system, not a strawman.

If the learned policy cannot beat that, the honest conclusion is that the
cleverness was not worth it -- and the evaluation is built to be able to say so.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from kintsugi.compliance import (
    CARD_WINDOW_MINUTES, RuleBook, Scheme, constrain, scheme_for,
)
from kintsugi.domain import (
    Action, ActionKind, Channel, Disposition, FailureClass, Minute, Payment,
    Rail,
)

HOUR = 60
DAY = 1440


@runtime_checkable
class RecoveryPolicy(Protocol):
    """The interface every policy implements.

    ``decide`` is called whenever a payment is open and due for a decision. It
    receives only the observable :class:`~kintsugi.domain.Payment` record --
    never the simulator's latent state.
    """

    name: str

    def decide(self, payment: Payment, now: Minute, ctx) -> Action: ...


class NoRecoveryPolicy:
    """Write off on first failure. The floor: what you keep by doing nothing."""

    name = "no_recovery"

    def decide(self, payment: Payment, now: Minute, ctx) -> Action:
        return Action.abandon("no recovery attempted")


class FixedRetryPolicy:
    """Retry on a fixed schedule and send fixed dunning messages.

    This is the industry default and the honest baseline: most subscription
    and checkout stacks retry at preset offsets and send a preset sequence of
    reminders, with no reference to *why* the payment failed. It is not
    stupid -- it recovers real money -- it is just blind.
    """

    name = "fixed_retry"

    def __init__(
        self,
        retry_offsets: tuple[int, ...] = (1 * HOUR, 1 * DAY, 3 * DAY),
        nudge_offsets: tuple[int, ...] = (2 * HOUR, 2 * DAY),
        channel: Channel = Channel.SMS,
    ) -> None:
        self.retry_offsets = retry_offsets
        self.nudge_offsets = nudge_offsets
        self.channel = channel

    def decide(self, payment: Payment, now: Minute, ctx) -> Action:
        age = payment.age(now)

        # Fire whichever scheduled event is next due, retries before nudges.
        for i, offset in enumerate(self.retry_offsets):
            if payment.retry_count == i and age >= offset:
                return Action.retry(
                    payment.preferred_rail,
                    f"scheduled retry #{i + 1} at +{offset // 60}h",
                )
        for i, offset in enumerate(self.nudge_offsets):
            if payment.nudge_count == i and age >= offset:
                return Action.nudge(
                    self.channel, f"scheduled reminder #{i + 1}")

        pending = [o for o in (*self.retry_offsets, *self.nudge_offsets) if o > age]
        if not pending:
            return Action.abandon("schedule exhausted")
        return Action.wait(recheck_in=max(5, min(pending) - age),
                           rationale="waiting for next scheduled event")


class RuleBasedPolicy:
    """A strong, hand-written, cause-aware policy.

    Encodes what an experienced payments engineer knows:

    * A dead instrument is dead. Stop immediately; every further attempt is
      pure cost and irritation.
    * Issuer incidents resolve in tens of minutes. Wait them out, and prefer a
      different rail if the customer has one.
    * Balance problems resolve on the salary cycle, not on a 24-hour timer.
    * If the customer is the blocker, no server-side retry can help. Ask them
      back -- during waking hours -- and accept the answer if they decline.
    """

    name = "rule_based"

    def __init__(self) -> None:
        # Scheme rules are mandatory, so the serious baseline implements them
        # too. Reserving them for the learned agent would manufacture a lead
        # that has nothing to do with decision quality.
        self.rulebook = RuleBook()
        self._card_attempts: dict[str, list[int]] = {}

    def reset(self) -> None:
        self.rulebook.reset()
        self._card_attempts.clear()

    MAX_RETRIES = 4
    MAX_NUDGES = 3
    MAX_REPROMPTS = 4

    def decide(self, payment: Payment, now: Minute, ctx) -> Action:
        history = self._card_attempts.get(payment.customer_id, [])
        cutoff = now - CARD_WINDOW_MINUTES
        on_instrument = sum(1 for at in history if at >= cutoff)

        action = constrain(self._decide(payment, now, ctx), payment, now,
                           self.rulebook, on_instrument)
        if action.kind is ActionKind.RETRY \
                and scheme_for(payment) is Scheme.CARD:
            self._card_attempts.setdefault(payment.customer_id, []).append(now)
        return action

    def _decide(self, payment: Payment, now: Minute, ctx) -> Action:
        cause = payment.last_failure_class
        if cause is None:
            return Action.wait(HOUR, "no failure on record")

        if cause.is_terminal:
            return Action.abandon(
                f"{cause.name} is terminal; no retry can succeed")

        if payment.retry_count >= self.MAX_RETRIES:
            return Action.abandon("retry budget exhausted")

        disposition = cause.disposition

        if disposition is Disposition.RAIL_SWITCH:
            return self._infrastructure(payment, now, cause)
        if disposition is Disposition.TIME_HEALS:
            return self._balance(payment, now, cause)
        if disposition is Disposition.NEEDS_CUSTOMER:
            return self._customer(payment, now, cause)

        return Action.wait(4 * HOUR, "unmapped cause; conservative wait")

    # -- branches --------------------------------------------------------

    @staticmethod
    def _infrastructure(payment: Payment, now: Minute, cause: FailureClass) -> Action:
        """Wait out the incident, escalating the wait each time."""
        waited = payment.minutes_since_last_attempt(now)
        backoff = (30, 90, 240, 480)
        target = backoff[min(payment.retry_count, len(backoff) - 1)]
        if waited < target:
            return Action.wait(target - waited,
                               f"{cause.name}: waiting {target}m for recovery")

        # Prefer a rail that does not depend on the impaired issuer path.
        alt = _alternate_rail(payment.preferred_rail)
        if payment.retry_count >= 1 and alt is not None:
            return Action.retry(alt, f"{cause.name}: switching to {alt.name}")
        return Action.retry(payment.preferred_rail,
                            f"{cause.name}: retrying after backoff")

    @staticmethod
    def _balance(payment: Payment, now: Minute, cause: FailureClass) -> Action:
        """Retry when money is most likely to have arrived.

        Salary credit clusters at the start of the month, so if that is near,
        wait for it rather than burning an attempt against an empty account.
        """
        day_of_month = (now // DAY) % 30
        waited = payment.minutes_since_last_attempt(now)

        days_to_payday = (30 - day_of_month) % 30
        if 0 < days_to_payday <= 4 and payment.retry_count >= 1:
            return Action.wait(
                days_to_payday * DAY + 6 * HOUR,
                f"{cause.name}: holding for month-start salary credit",
            )

        schedule = (1 * DAY, 3 * DAY, 7 * DAY)
        target = schedule[min(payment.retry_count, len(schedule) - 1)]
        if waited < target:
            return Action.wait(
                target - waited,
                f"{cause.name}: waiting {target // DAY}d for balance to recover")
        return Action.retry(payment.preferred_rail,
                            f"{cause.name}: retrying after balance window")

    def _customer(self, payment: Payment, now: Minute, cause: FailureClass) -> Action:
        """The customer has to come back. Two levers, not one.

        A first version of this policy only sent reminders here, on the
        reasoning that "no server-side retry can succeed if the customer never
        authenticated". That reasoning is wrong on the rails that carry most of
        India's volume. On UPI a retry *is* a fresh prompt -- a new collect
        request or intent lands in the payer's app -- so re-prompting is a real
        recovery action, not a wasted attempt. Holding that mistaken assumption
        cost this baseline about 94 points of recovery on ``AUTH_ABANDONED``,
        and it would have flattered the learned agent enormously.

        So: re-prompt on rails where a retry reaches the customer, remind
        alongside it, and do both only during waking hours.
        """
        hour = (now // 60) % 24
        if hour < 9 or hour >= 21:
            minutes_to_morning = ((9 - hour) % 24) * HOUR
            return Action.wait(minutes_to_morning,
                               "holding contact until waking hours")

        if payment.preferred_rail.requires_customer_present:
            backoff = (30, 3 * HOUR, 12 * HOUR, 1 * DAY)
            target = backoff[min(payment.retry_count, len(backoff) - 1)]
            if (payment.retry_count < self.MAX_REPROMPTS
                    and payment.minutes_since_last_attempt(now) >= target):
                return Action.retry(
                    payment.preferred_rail,
                    f"{cause.name}: re-prompting the customer on "
                    f"{payment.preferred_rail.name}")

        if payment.nudge_count >= self.MAX_NUDGES:
            if payment.retry_count >= self.MAX_REPROMPTS:
                return Action.abandon("customer contacted enough; standing down")
            return Action.wait(2 * HOUR, "waiting to re-prompt")

        spacing = (45, 1 * DAY, 3 * DAY)
        target = spacing[min(payment.nudge_count, len(spacing) - 1)]
        if payment.nudge_count > 0 \
                and payment.minutes_since_last_nudge(now) < target:
            return Action.wait(
                min(4 * HOUR, target - payment.minutes_since_last_nudge(now)),
                "spacing customer contact")

        channel = Channel.SMS if payment.nudge_count == 0 else Channel.WHATSAPP
        return Action.nudge(
            channel, f"{cause.name}: asking the customer to re-authenticate")


def _alternate_rail(rail: Rail) -> Rail | None:
    """A different path to the same money."""
    return _ALTERNATES.get(rail)


_ALTERNATES: dict[Rail, Rail] = {
    Rail.UPI_COLLECT: Rail.UPI_INTENT,
    Rail.UPI_INTENT: Rail.CARD,
    Rail.NETBANKING: Rail.UPI_INTENT,
    Rail.CARD: Rail.UPI_INTENT,
    Rail.WALLET: Rail.UPI_INTENT,
}
