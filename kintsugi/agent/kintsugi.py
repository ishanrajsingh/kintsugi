"""The Kintsugi recovery agent.

The decision, stated plainly
---------------------------
For each open payment the agent asks: *what is the most valuable thing I could
do about this, and is now the moment to do it?* It answers by pricing every
available action in rupees --

    EV(retry)  = P(authorises now) x amount  -  attempt cost
    EV(nudge)  = P(money arrives) x amount  -  send cost  -  churn risk x amount
    EV(wait t) = best EV available at t, discounted for the risk of expiry
    EV(stop)   = 0

-- and taking the largest. Waiting is a first-class action evaluated against
future moments, not a default gap between retries. That is the whole difference
from a fixed schedule: a schedule asks "has enough time passed?", while this
asks "is there a better moment coming, and is it worth waiting for?" For an
``INSUFFICIENT_FUNDS`` failure on the 26th, the answer is usually yes -- payday
is worth more than any number of retries before it.

Where the LLM is, and is not
----------------------------
The language model normalises messy gateway strings into the taxonomy upstream
of this file, and writes the customer-facing copy downstream of it. It does not
choose actions. Deciding which payment to chase is a calibrated-probability
problem against a cost model, and a language model asked to do it would produce
fluent, confident, unpriced guesses. Keeping it out of the loop is a design
decision, not an omission.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from kintsugi import calibration as cal
from kintsugi.agent.features import extract
from kintsugi.agent.health_monitor import IssuerHealthMonitor
from kintsugi.agent.policy import _ALTERNATES
from kintsugi.agent.predictor import Predictor
from kintsugi.domain import (
    Action, Channel, Disposition, Minute, Payment, Rail,
)

HOUR = 60
DAY = 1440


@dataclass(slots=True)
class AgentConfig:
    max_retries: int = 6
    max_nudges: int = 3
    payment_ttl_minutes: int = 14 * DAY

    min_ev_paise: float = 0.0
    """Act only when an action's expected value clears this. Zero means "act
    whenever it pays for itself"; raising it makes the agent stingier."""

    wait_discount_per_day: float = 0.012
    """Money later is worth slightly less, and a payment left open is a payment
    that might expire. Small: over a fortnight it costs ~17%, enough to break
    ties toward acting sooner without making the agent impatient."""

    churn_risk_per_extra_nudge: float = 0.11
    """Policy-side prior on the chance a further message drives the customer
    away entirely, once past the free allowance. The agent cannot see the
    latent patience budget, so it carries a documented prior instead --
    deliberately pessimistic, because the downside is losing the whole
    payment."""

    churn_free_nudges: int = 2
    """Free allowance, counted **per customer**, not per payment."""

    contact_goodwill_price_paise: float = 5_000.0
    """What one customer contact costs *beyond* the price of sending it.

    Default INR 50, chosen by sweeping this value on tuning seeds 11-15, which
    are disjoint from the evaluation seeds. It is a design parameter, so it gets
    the same seed discipline as the detector thresholds: picked on worlds the
    reported numbers are not measured on.

    An SMS costs 20 paise. Pricing only that is why expected-value systems
    spam: against a payment worth hundreds of rupees, almost any contact clears
    a 20-paise bar, so the arithmetic says message everyone forever. What it
    misses is that attention is not free to the business either -- reputation,
    unsubscribes, app uninstalls, and the slow erosion of every future message's
    effectiveness. None of that appears on the telecom invoice.

    Setting this above zero trades recovery for restraint along a smooth
    frontier; ``scripts/run_contact_frontier.py`` measures it. Zero reproduces
    the unconstrained agent -- which sends roughly 60% more messages for
    slightly *less* recovered value, because over-contacting is destructive
    rather than merely wasteful."""

    contact_window_minutes: int = 14 * DAY
    """How far back customer contact is remembered when pricing churn."""

    max_contacts_per_customer: int = 4
    """Hard frequency cap per customer per window.

    Every real dunning system has one, for a reason the expected-value
    arithmetic misses on its own: a message costs 20-35 paise against a
    payment often worth hundreds of rupees, so on price alone almost any
    contact clears its cost and the agent will message forever. The true cost
    of contact is goodwill, which is spent per *person* and shared across every
    payment that person owes -- so it has to be capped per person too."""

    candidate_offsets: tuple[int, ...] = (
        30, 2 * HOUR, 6 * HOUR, 12 * HOUR,
        1 * DAY, 2 * DAY, 3 * DAY, 5 * DAY, 7 * DAY, 10 * DAY,
    )
    """Future moments considered when deciding whether to wait. Spaced roughly
    geometrically because the mechanisms live on different timescales: outages
    resolve in tens of minutes, balances on the salary cycle."""

    consider_payday: bool = True
    """Add the next month-start as an explicit candidate. The salary credit is
    the single largest timing effect in Indian collections and it does not fall
    on a geometric grid."""

    use_monitor: bool = True
    """Whether to scale retry probability by the inferred issuer health.
    Switched off in the ablation study to isolate what the detector is worth."""


class KintsugiPolicy:
    """Expected-value recovery agent."""

    name = "kintsugi"

    def __init__(
        self,
        retry_model: Predictor | None = None,
        nudge_model: Predictor | None = None,
        config: AgentConfig | None = None,
        monitor: IssuerHealthMonitor | None = None,
    ) -> None:
        self.cfg = config or AgentConfig()
        self.retry_model = retry_model or Predictor.load("retry")
        self.nudge_model = nudge_model or Predictor.load("nudge")
        self.monitor = monitor or IssuerHealthMonitor()
        self.decisions: list[dict] = []
        """Decision log. Every action carries the priced alternatives that lost,
        which is what the merchant-facing explanation surface reads back."""

        self._contacts: dict[str, list[int]] = {}
        """When each customer was last contacted, across all their payments.

        Contact fatigue belongs to the person, not the invoice. Tracking it
        per payment -- which this agent did first -- lets a customer who owes
        three payments be messaged three times over while each payment
        believes it has spent only one contact."""

    def reset(self) -> None:
        self.monitor.reset()
        self.decisions.clear()
        self._contacts.clear()

    def observe(self, payment: Payment, attempt, now: Minute) -> None:
        self.monitor.observe(
            payment.issuer, now, attempt.succeeded, attempt.failure_class)

    # -- the decision ----------------------------------------------------

    def decide(self, payment: Payment, now: Minute, ctx) -> Action:
        cause = payment.last_failure_class
        if cause is None:
            return Action.wait(HOUR, "no failure on record")

        # Terminal instruments are settled by the taxonomy, not by the model.
        # No probability estimate should be able to talk the agent into
        # retrying a closed account, and a model asked about a case that never
        # succeeds in training has nothing useful to say anyway.
        if cause.is_terminal:
            return Action.abandon(
                f"{cause.name} is terminal: no retry or reminder can recover "
                f"this instrument. Recovery requires new payment details.")

        if payment.retry_count >= self.cfg.max_retries:
            return Action.abandon("retry budget exhausted")

        amount = payment.amount_paise
        deadline = payment.created_at + self.cfg.payment_ttl_minutes

        # Every moment worth considering, now first.
        times = [now] + self._candidate_times(payment, now, deadline)
        rails = self._candidate_rails(payment)
        can_nudge = (payment.nudge_count < self.cfg.max_nudges
                     and self._contact_budget_left(payment, now))

        state = self.monitor.state(payment.issuer)
        issuer_mult = (self.monitor.success_multiplier(payment.issuer)
                       if self.cfg.use_monitor else 1.0)

        # Build every feature vector for every (moment, rail) pair up front and
        # score them in two batched calls. Scoring them one at a time is the
        # obvious implementation and is roughly fifty times slower -- the agent
        # evaluates ~11 moments x 2 rails plus 3 channels on every decision.
        rows: list[np.ndarray] = []
        for at in times:
            impaired = self.monitor.impaired_minutes(payment.issuer, at)
            for rail in rails:
                rows.append(extract(payment, at, rail, issuer_state=state,
                                    issuer_impaired_minutes=impaired))
        X = np.asarray(rows, dtype=np.float32)
        p_retry = self.retry_model.predict_batch(X).reshape(len(times), len(rails))

        if can_nudge:
            # The nudge features do not depend on the rail under consideration.
            nudge_rows = X[::len(rails)]
            p_nudge = self.nudge_model.predict_batch(nudge_rows)
        else:
            p_nudge = np.zeros(len(times), dtype=np.float64)

        churn = self._churn_risk(payment, now)
        discounts = np.array(
            [self._discount(at - now) for at in times], dtype=np.float64)

        # --- price everything --------------------------------------------
        retry_ev = p_retry.copy()
        # Scaling the preferred rail by the monitor's belief adds structural
        # knowledge the model cannot learn reliably: outages are rare and short,
        # so training rows taken during them are few, but the consequence of
        # retrying into a dead bank is certain.
        retry_ev[:, 0] *= issuer_mult
        retry_p = retry_ev.copy()
        retry_ev = retry_ev * amount - cal.RETRY_ATTEMPT_COST_PAISE.v

        channels = list(Channel)
        chan_mult = np.array([_CHANNEL_EFFECTIVENESS[c] for c in channels])
        chan_cost = np.array([c.cost_paise for c in channels], dtype=np.float64)
        nudge_p = p_nudge[:, None] * chan_mult[None, :]
        nudge_ev = (nudge_p * amount - chan_cost[None, :]
                    - self.cfg.contact_goodwill_price_paise
                    - churn * amount * _RESIDUAL_VALUE_IF_CHURNED)
        if not can_nudge:
            nudge_ev[:] = -np.inf

        # Best action at each moment, then the best moment.
        best_retry_rail = retry_ev.argmax(axis=1)
        best_retry_ev = retry_ev[np.arange(len(times)), best_retry_rail]
        best_chan = nudge_ev.argmax(axis=1)
        best_nudge_ev = nudge_ev[np.arange(len(times)), best_chan]

        immediate_ev = np.maximum(best_retry_ev, best_nudge_ev)
        # Discount gains only. Applying a <1 factor to a negative expected value
        # makes a future loss look *smaller* than the same loss taken now, which
        # would have the agent wait its way toward options it has already priced
        # as not worth taking. The min-EV guard below happens to mask this, but
        # relying on a downstream guard to hide an incorrect quantity is how the
        # bug survives the next refactor.
        discounted = np.where(immediate_ev > 0, immediate_ev * discounts,
                              immediate_ev)

        now_ev = float(immediate_ev[0])

        # --- wait, act, or stop -------------------------------------------
        #
        # Acting now and acting later are **not** mutually exclusive, and an
        # earlier version of this agent compared them as though they were. That
        # is wrong in a way that costs real money: if the retry fires now and
        # fails, the better moment is still there afterwards. Waiting gives up
        # an option for nothing.
        #
        # So the comparison is between
        #
        #     act now  =  EV(now)  +  P(now fails) x V(best future moment)
        #     wait     =                            V(best future moment)
        #
        # which reduces to acting whenever ``EV(now) > P(now succeeds) x
        # V(future)`` -- i.e. wait only when succeeding now would *forfeit*
        # more future value than acting now is worth. With retries costing 15
        # paise against payments worth hundreds of rupees, that condition is
        # usually false, and the agent should act and re-evaluate rather than
        # hold. Treating them as exclusive made it defer itself past the
        # payment's expiry: it recovered 76.2% where a fixed-schedule rules
        # policy recovered 78.1%, purely by waiting for moments it then never
        # used.
        future = discounted[1:]
        if len(future):
            best_future_idx = int(future.argmax()) + 1
            best_future_ev = float(discounted[best_future_idx])
        else:
            best_future_idx, best_future_ev = 0, 0.0

        p_now = float(max(retry_p[0].max(),
                          nudge_p[0].max() if can_nudge else 0.0))
        act_now_value = now_ev + (1.0 - p_now) * max(0.0, best_future_ev)

        if best_future_idx and best_future_ev > act_now_value \
                and best_future_ev > self.cfg.min_ev_paise:
            best_idx = best_future_idx
            delay = times[best_idx] - now
            action = Action.wait(
                delay,
                self._explain_wait(cause, act_now_value, best_future_ev, delay),
                ev=best_future_ev,
            )
            # Deliberate waits are logged like any other action. A decision to
            # hold a payment for six days *is* a decision, and it is the one a
            # merchant is most likely to question -- so it has to be in the
            # ledger with its price, not inferred from a gap in the record.
            self._log(payment, now, action, float(discounted[best_idx]),
                      self._alternatives(rails, channels, retry_p, retry_ev,
                                         nudge_p, nudge_ev, can_nudge))
            return action

        if now_ev <= self.cfg.min_ev_paise:
            return Action.abandon(
                f"no action is worth its cost: best option valued at "
                f"{now_ev / 100:,.2f} INR against a {amount / 100:,.2f} INR claim")

        # Materialise the winning action at `now`.
        if best_retry_ev[0] >= best_nudge_ev[0]:
            rail = rails[int(best_retry_rail[0])]
            action = Action.retry(
                rail,
                f"{cause.name}: retry on {rail.name} at "
                f"P(success)={retry_p[0, int(best_retry_rail[0])]:.0%}",
                ev=now_ev,
            )
        else:
            channel = channels[int(best_chan[0])]
            self._contacts.setdefault(payment.customer_id, []).append(now)
            action = Action.nudge(
                channel,
                f"{cause.name}: {channel.name} reminder at "
                f"P(recovery)={nudge_p[0, int(best_chan[0])]:.0%}",
                ev=now_ev,
            )

        self._log(payment, now, action, now_ev,
                  self._alternatives(rails, channels, retry_p, retry_ev,
                                     nudge_p, nudge_ev, can_nudge))
        return action

    @staticmethod
    def _alternatives(rails, channels, retry_p, retry_ev, nudge_p, nudge_ev,
                      can_nudge) -> list[dict]:
        """The priced options that lost, for the explanation surface."""
        alts = [
            {"action": f"retry:{rail.name}",
             "p": float(retry_p[0, i]), "ev_paise": float(retry_ev[0, i])}
            for i, rail in enumerate(rails)
        ]
        if can_nudge:
            alts += [
                {"action": f"nudge:{ch.name}",
                 "p": float(nudge_p[0, i]), "ev_paise": float(nudge_ev[0, i])}
                for i, ch in enumerate(channels)
            ]
        alts.sort(key=lambda d: d["ev_paise"], reverse=True)
        return alts

    def _candidate_rails(self, payment: Payment) -> list[Rail]:
        """The original rail, plus one alternative when switching makes sense.

        Only offered for infrastructure and risk failures. Switching rails does
        not conjure a balance, so offering it for ``INSUFFICIENT_FUNDS`` would
        just invite the model to spend an attempt on a different door into the
        same empty account.
        """
        rails = [payment.preferred_rail]
        cause = payment.last_failure_class
        if cause and cause.disposition is Disposition.RAIL_SWITCH:
            alt = _ALTERNATES.get(payment.preferred_rail)
            if alt is not None and not payment.is_recurring:
                rails.append(alt)
        return rails

    def _recent_contacts(self, payment: Payment, now: Minute) -> int:
        """Messages sent to this customer recently, across every payment."""
        history = self._contacts.get(payment.customer_id)
        if not history:
            return payment.nudge_count
        cutoff = now - self.cfg.contact_window_minutes
        return sum(1 for at in history if at >= cutoff)

    def _churn_risk(self, payment: Payment, now: Minute) -> float:
        excess = max(0, self._recent_contacts(payment, now)
                     - self.cfg.churn_free_nudges)
        return min(0.45, excess * self.cfg.churn_risk_per_extra_nudge)

    def _contact_budget_left(self, payment: Payment, now: Minute) -> bool:
        return (self._recent_contacts(payment, now)
                < self.cfg.max_contacts_per_customer)

    def _candidate_times(
        self, payment: Payment, now: Minute, deadline: Minute
    ) -> list[Minute]:
        times = [now + off for off in self.cfg.candidate_offsets]
        if self.cfg.consider_payday:
            day = now // DAY
            days_to_month_start = (30 - (day % 30)) % 30
            if days_to_month_start == 0:
                days_to_month_start = 30
            # Late morning on the 1st: salary has landed and the customer is awake.
            times.append(now + days_to_month_start * DAY + 10 * HOUR)
        return [t for t in times if t < deadline]

    def _discount(self, delay: Minute) -> float:
        return max(0.0, 1.0 - self.cfg.wait_discount_per_day * (delay / DAY))

    # -- explanation -----------------------------------------------------

    @staticmethod
    def _explain_wait(cause, now_ev: float, future_ev: float, delay: int) -> str:
        if delay >= DAY:
            when = f"{delay / DAY:.1f} days"
        else:
            when = f"{delay / HOUR:.1f} hours"
        return (
            f"{cause.name}: holding {when}. Acting now is worth "
            f"{_rupees(now_ev)} INR; waiting is worth {_rupees(future_ev)} INR."
        )

    def _log(self, payment, now, action, ev, alternatives) -> None:
        self.decisions.append({
            "payment_id": payment.payment_id,
            "at": now,
            "amount_paise": payment.amount_paise,
            "cause": payment.last_failure_class.name if payment.last_failure_class else None,
            "chosen": action.kind.name,
            "rail": action.rail.name if action.rail else None,
            "channel": action.channel.name if action.channel else None,
            "ev_paise": ev,
            "rationale": action.rationale,
            "alternatives": alternatives[:5],
        })


def _rupees(paise: float) -> str:
    """Format paise as rupees, without emitting "-0".

    Expected values legitimately land fractionally below zero, and a minus sign
    in front of nothing reads to a merchant like a bug in the engine.
    """
    rupees = paise / 100
    if abs(rupees) < 0.5:
        rupees = 0.0
    return f"{rupees:,.0f}"


#: Relative effectiveness of each channel at actually reaching a person. The
#: nudge model is trained across all channels, so this rescales its average
#: prediction to the specific channel under consideration.
_CHANNEL_EFFECTIVENESS: dict[Channel, float] = {
    Channel.EMAIL: 0.62,
    Channel.SMS: 1.00,
    Channel.WHATSAPP: 1.22,
}

#: If over-contact drives a customer away, some value may still be recoverable
#: later through other means. Not all of the claim is lost, so the churn
#: penalty is scaled rather than charged at face value.
_RESIDUAL_VALUE_IF_CHURNED = 0.75
