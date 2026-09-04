"""A randomised policy whose only job is generating unbiased training data.

You can't learn this from the rule-based policy's logs, because they contain
almost no information about the decisions that matter. That policy retries
balance failures at +1d, +3d and +7d, so in its logs INSUFFICIENT_FUNDS retries
occur only at those three delays. A model trained on it has never seen a balance
retry at +4h and can't learn whether one would have worked -- yet the moment the
learned policy ships it gets asked exactly that, and the gaps get filled by
confident, unfounded extrapolation.

Standard off-policy trap: a policy's own logs have no support where the policy
never acts. Standard fix: collect under something that randomises across the
action space, so every region the learned policy might later visit has real
outcomes in it.

So the explorer deliberately plays badly. It retries at absurd hours, nudges
customers who obviously can't pay, and gives up on payments it should chase. Its
recovery rate is poor and that's fine -- it's a measuring instrument, not a
candidate.
"""

from __future__ import annotations

from kintsugi.domain import Action, Channel, Minute, Payment, Rail
from kintsugi.rng import uniform

# The action space is sampled log-uniformly in delay, because the interesting
# structure spans minutes (outage recovery) to days (the salary cycle), and a
# uniform sample over that range would put almost nothing in the first hours.
_MIN_DELAY = 15
_MAX_DELAY = 14 * 1440


class ExplorationPolicy:
    """Uniformly random actions over the full decision space."""

    name = "explorer"

    def __init__(
        self,
        seed: int = 999,
        p_retry: float = 0.45,
        p_nudge: float = 0.30,
        p_wait: float = 0.20,
        p_abandon: float = 0.05,
        max_actions: int = 8,
    ) -> None:
        self.seed = seed
        weights = (p_retry, p_nudge, p_wait, p_abandon)
        total = sum(weights)
        self.thresholds = []
        running = 0.0
        for w in weights:
            running += w / total
            self.thresholds.append(running)
        self.max_actions = max_actions

    def decide(self, payment: Payment, now: Minute, ctx) -> Action:
        pid = payment.payment_id
        step = payment.retry_count + payment.nudge_count

        # A budget, not a strategy: without it the explorer would hammer some
        # payments hundreds of times and the dataset would be dominated by
        # deep-retry states that no sane policy ever reaches.
        if step >= self.max_actions:
            return Action.abandon("exploration budget spent")

        u = uniform(self.seed, "explore_kind", pid, step)
        delay = self._delay(pid, step)

        if u < self.thresholds[0]:
            rail = self._rail(payment, pid, step)
            return Action.retry(rail, "exploration: random retry")
        if u < self.thresholds[1]:
            channel = self._channel(pid, step)
            return Action.nudge(channel, "exploration: random nudge")
        if u < self.thresholds[2]:
            return Action.wait(delay, "exploration: random wait")
        return Action.abandon("exploration: random abandon")

    # -- random draws ----------------------------------------------------

    def _delay(self, pid: str, step: int) -> int:
        u = uniform(self.seed, "explore_delay", pid, step)
        # log-uniform across 15 minutes .. 14 days
        ratio = _MAX_DELAY / _MIN_DELAY
        return int(_MIN_DELAY * (ratio ** u))

    def _rail(self, payment: Payment, pid: str, step: int) -> Rail:
        u = uniform(self.seed, "explore_rail", pid, step)
        rails = list(Rail)
        # Keep the original rail well represented -- it is what a real system
        # would mostly do -- while still covering every alternative.
        if u < 0.55:
            return payment.preferred_rail
        return rails[int(uniform(self.seed, "explore_rail2", pid, step) * len(rails))]

    def _channel(self, pid: str, step: int) -> Channel:
        channels = list(Channel)
        u = uniform(self.seed, "explore_chan", pid, step)
        return channels[int(u * len(channels))]


class ScheduledExplorationPolicy(ExplorationPolicy):
    """Explorer variant that always waits a random delay before acting.

    Pairs with the base explorer to widen coverage of the *timing* dimension
    specifically. The base explorer acts as soon as it is consulted, which
    concentrates its retries shortly after each failure; this one spreads them
    across the whole fortnight, which is where the salary-cycle signal lives.
    """

    name = "explorer_scheduled"

    def decide(self, payment: Payment, now: Minute, ctx) -> Action:
        pid = payment.payment_id
        step = payment.retry_count + payment.nudge_count
        if step >= self.max_actions:
            return Action.abandon("exploration budget spent")

        # Alternate: wait a random interval, then act on the next consultation.
        waited = payment.minutes_since_last_attempt(now)
        target = self._delay(pid, step)
        if waited < target and payment.retry_count + payment.nudge_count == step:
            if uniform(self.seed, "explore_hold", pid, step, waited // 60) < 0.7:
                return Action.wait(
                    min(720, target - waited), "exploration: scheduled hold")
        return super().decide(payment, now, ctx)
