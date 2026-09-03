"""The simulated payments world.

Failure generation is **cause-first**. Rather than sampling "does this fail?"
and then "why did it fail?" from a static table, each attempt runs a competing-
risks race between hazards that are themselves functions of latent state: the
issuer's health right now, this customer's balance right now, whether the card
is actually dead, whether anyone is awake to approve a collect request.

That distinction is the whole ballgame. Under table-sampling, a retry is just
another draw from the same distribution, so *every* policy that retries more
recovers more and the evaluation is meaningless. Under cause-first generation,
a retry succeeds only if the condition that caused the failure has actually
changed -- the outage ended, payday landed, the customer came back. A policy
earns lift by predicting when that is true, which is the real problem.

The hazard scales are not hand-tuned. They are fitted (see
:mod:`kintsugi.world.fitting`) so that the marginal failure rate and the
cause mix this generator produces match the calibrated targets.
"""

from __future__ import annotations

import heapq
from dataclasses import dataclass, field

from kintsugi import calibration as cal
from kintsugi.domain import (
    Action, ActionKind, Attempt, Channel, FailureClass, Minute, Nudge,
    Paise, Payment, Rail,
)
from kintsugi.rng import bernoulli, choice, uniform
from kintsugi.world.customers import CustomerPopulation, MINUTES_PER_DAY
from kintsugi.world.issuers import DEFAULT_ISSUERS, HealthState, IssuerRegistry

# Failure classes whose cause is a permanent property of the instrument.
# Once true, no retry on any rail at any time can succeed.
TERMINAL_CLASSES = (
    FailureClass.ACCOUNT_CLOSED,
    FailureClass.CARD_BLOCKED,
    FailureClass.INVALID_INSTRUMENT,
    FailureClass.MANDATE_REVOKED,
)


@dataclass(slots=True)
class WorldConfig:
    horizon_days: int = 30
    n_customers: int = 4_000
    n_payments: int = 12_000
    mandate_share: float = 0.30
    """Fraction of payments that are server-initiated recurring debits."""
    payment_ttl_days: int = 14
    """How long a merchant keeps chasing before writing the payment off."""
    seed: int = 7
    max_attempts: int = 12
    """Hard safety ceiling. Policies are expected to stop long before this."""

    @property
    def horizon_minutes(self) -> int:
        return self.horizon_days * MINUTES_PER_DAY


@dataclass(slots=True)
class LedgerEntry:
    """One decision, with everything needed to audit it afterwards."""

    at: Minute
    payment_id: str
    action: ActionKind
    rail: Rail | None
    channel: Channel | None
    rationale: str
    expected_value_paise: float
    outcome: str
    cost_paise: Paise


@dataclass(slots=True)
class SimulationResult:
    policy_name: str
    config: WorldConfig
    payments: list[Payment]
    ledger: list[LedgerEntry] = field(default_factory=list)
    issuer_downtime: dict[str, int] = field(default_factory=dict)


class World:
    """One simulated payments environment.

    Latent state (issuer health, customer balances, dead instruments) is built
    once at construction and is identical for every policy run against this
    world. :meth:`run` resets only the state a policy is allowed to influence.
    """

    def __init__(
        self,
        config: WorldConfig,
        hazard_scales: dict | None = None,
        segment_params: dict | None = None,
    ):
        self.cfg = config
        self.seed = config.seed
        # Hazard scales are fitted **per segment**. Checkout and scheduled
        # mandate debits have genuinely different published authorisation rates
        # *and* different published cause mixes, and a single shared scale per
        # cause cannot satisfy both -- trying to force it drives the fit onto
        # its bounds and silently distorts the checkout mix. Two independent
        # scale sets make the calibration well posed.
        fitted_scales, fitted_segment = _load_fitted_once()
        sp = segment_params if segment_params is not None else (fitted_segment or {})
        self.checkout_selection_bonus = sp.get(
            "checkout_selection_bonus", _CHECKOUT_SELECTION_BONUS)
        self.issuers = IssuerRegistry(config.horizon_minutes, config.seed)
        codes = [i.code for i in DEFAULT_ISSUERS]
        weights = [i.share for i in DEFAULT_ISSUERS]
        self.population = CustomerPopulation(
            config.n_customers, config.seed, codes, weights)
        if hazard_scales is None:
            hazard_scales = fitted_scales or {
                "checkout": DEFAULT_HAZARD_SCALES.copy(),
                "mandate": DEFAULT_HAZARD_SCALES.copy(),
            }
        self.hazard_scales = {
            "checkout": dict(hazard_scales["checkout"]),
            "mandate": dict(hazard_scales["mandate"]),
        }
        self._template = self._generate_payments()

    # -- payment generation ---------------------------------------------

    def _generate_payments(self) -> list[Payment]:
        """Pre-generate every payment obligation in the horizon.

        Arrivals, amounts, rails and payer are all latent and policy-
        independent, so they are fixed here once for all policies.
        """
        cfg = self.cfg
        payments: list[Payment] = []
        for i in range(cfg.n_payments):
            customer = self.population.by_index(
                int(uniform(self.seed, "pay_cust", i) * len(self.population)))

            is_mandate = uniform(self.seed, "pay_mandate", i) < cfg.mandate_share

            if is_mandate:
                rail = Rail.CARD if uniform(self.seed, "pay_mrail", i) < 0.4 \
                    else Rail.UPI_INTENT
                # Recurring debits fire on a monthly cycle, clustered in the
                # first days of the month like real subscription billing.
                day = int(uniform(self.seed, "pay_mday", i) * 5)
                minute = day * MINUTES_PER_DAY + int(
                    uniform(self.seed, "pay_mmin", i) * MINUTES_PER_DAY)
            else:
                rail = choice(_CHECKOUT_RAIL_MIX, self.seed, "pay_rail", i)
                minute = int(uniform(self.seed, "pay_t", i) * cfg.horizon_minutes)

            # Amount around the customer's typical, log-scattered.
            scatter = 10 ** (uniform(self.seed, "pay_amt", i) * 1.2 - 0.6)
            amount = max(1000, int(customer.typical_amount_paise * scatter))

            payments.append(Payment(
                payment_id=f"pay_{i:06d}",
                customer_id=customer.customer_id,
                merchant_id=f"merch_{i % 40:03d}",
                amount_paise=amount,
                preferred_rail=rail,
                issuer=customer.issuer_code,
                created_at=minute,
                is_recurring=is_mandate,
            ))
        payments.sort(key=lambda p: p.created_at)
        return payments

    def _is_mandate(self, payment: Payment) -> bool:
        return payment.is_recurring

    # -- attempt resolution ----------------------------------------------

    def resolve_attempt(
        self, payment: Payment, rail: Rail, now: Minute, attempt_no: int
    ) -> tuple[bool, FailureClass | None]:
        """Resolve one authorisation as a sequence of latent gates.

        Each gate asks a question about the *world*, not about the attempt, and
        each is keyed to the timescale on which that piece of the world
        actually changes:

        ==================  ==========================  ======================
        Gate                Keyed by                    So a retry...
        ==================  ==========================  ======================
        Instrument alive    payment                     never helps
        Issuer healthy      wall-clock health timeline  helps once it recovers
        Balance sufficient  payment + **day**           helps after payday
        Within limits       payment + **day**           helps tomorrow
        Risk accepted       payment + attempt           may help immediately
        Customer authorises payment + attempt + hour    helps if well timed
        Transport held      payment + attempt           may help immediately
        ==================  ==========================  ======================

        The keying is the entire point. Because the balance gate is keyed by
        day, retrying an ``INSUFFICIENT_FUNDS`` failure twenty minutes later
        draws the *same* value and fails again -- as it would in reality, since
        no money arrived in between. The only way to recover that payment is to
        wait for the salary credit. Under per-attempt keying the retry would
        succeed on a fresh roll, and a blind loop would beat every intelligent
        policy, which is exactly what the first version of this simulator did.
        """
        cust = self.population.get(payment.customer_id)
        pid = payment.payment_id
        is_mandate = self._is_mandate(payment)
        s = self.hazard_scales["mandate" if is_mandate else "checkout"]
        day = now // MINUTES_PER_DAY

        # --- Gate 1: is the instrument alive? -----------------------------
        # A permanent property of the payment, drawn once. If the card is dead
        # it is dead on every attempt on every rail forever, which is exactly
        # the waste a fixed retry schedule keeps paying for.
        for fc in TERMINAL_CLASSES:
            if fc is FailureClass.MANDATE_REVOKED and not is_mandate:
                continue
            if uniform(self.seed, "dead", pid, fc.name) < s[fc]:
                return False, fc

        # --- Gate 2: is the issuer up? ------------------------------------
        # Driven by the pre-computed health timeline, so it is identical for
        # every policy and depends only on when the attempt was made.
        state = self.issuers.state(payment.issuer, now)
        p_infra = min(1.0, _INFRA_FAIL_PROB[state] * s[FailureClass.ISSUER_DOWN])
        if bernoulli(p_infra, self.seed, "infra", pid, attempt_no):
            return False, FailureClass.ISSUER_DOWN

        # --- Gate 3: did the balance cover it? ----------------------------
        # Keyed by day: money does not arrive because a merchant retried.
        # Checkout gets a selection bonus -- the customer chose this moment to
        # pay -- while a scheduled mandate debit gets none. See
        # ``Customer.p_insufficient``.
        funds_scale = s[FailureClass.INSUFFICIENT_FUNDS]
        selection = 0.0 if is_mandate else self.checkout_selection_bonus
        p_short = cust.p_insufficient(
            now, payment.amount_paise, funds_scale, selection)
        if bernoulli(p_short, self.seed, "funds", pid, day):
            return False, FailureClass.INSUFFICIENT_FUNDS

        # --- Gate 4: within limits? ---------------------------------------
        # Also daily: per-day caps reset at midnight, not on retry.
        pressure = payment.amount_paise / max(1, cust.typical_amount_paise * 2)
        p_limit = min(1.0, s[FailureClass.LIMIT_EXCEEDED] * min(3.0, pressure))
        if bernoulli(p_limit, self.seed, "limit", pid, day):
            return False, FailureClass.LIMIT_EXCEEDED

        # --- Gate 5: did the risk engine accept? --------------------------
        # Per attempt: issuer risk decisions genuinely are re-evaluated, which
        # is why a soft decline is sometimes worth exactly one more try.
        p_risk = min(1.0, s[FailureClass.RISK_DECLINE] * (1.0 + min(2.0, pressure)))
        if bernoulli(p_risk, self.seed, "risk", pid, attempt_no):
            return False, FailureClass.RISK_DECLINE

        # --- Gate 6: did the customer complete authentication? ------------
        # Only exists when someone is present. Re-rollable per attempt and
        # strongly hour-dependent, so prompting again at a sensible hour is a
        # real lever -- and prompting at 3am is a real waste.
        if rail.requires_customer_present and not is_mandate:
            inattention = 1.0 - cust.attention_at(now)
            presence = 0.35 + 1.65 * inattention
            if bernoulli(min(1.0, s[FailureClass.AUTH_ABANDONED] * presence),
                         self.seed, "auth_ab", pid, attempt_no):
                return False, FailureClass.AUTH_ABANDONED
            if bernoulli(min(1.0, s[FailureClass.AUTH_TIMEOUT] * presence),
                         self.seed, "auth_to", pid, attempt_no):
                return False, FailureClass.AUTH_TIMEOUT
            if bernoulli(min(1.0, s[FailureClass.USER_CANCELLED]),
                         self.seed, "cancel", pid, attempt_no):
                return False, FailureClass.USER_CANCELLED

        # --- Gate 7: did the plumbing hold? -------------------------------
        if bernoulli(min(1.0, s[FailureClass.PSP_TIMEOUT]),
                     self.seed, "psp", pid, attempt_no):
            return False, FailureClass.PSP_TIMEOUT
        if bernoulli(min(1.0, s[FailureClass.NETWORK_TIMEOUT]),
                     self.seed, "net", pid, attempt_no):
            return False, FailureClass.NETWORK_TIMEOUT

        return True, None

    # -- execution -------------------------------------------------------

    def run(self, policy, collect_ledger: bool = True) -> SimulationResult:
        """Run one policy against this world."""
        cfg = self.cfg
        self.population.reset()
        if hasattr(policy, "reset"):
            policy.reset()

        payments = [
            Payment(
                payment_id=p.payment_id,
                customer_id=p.customer_id,
                merchant_id=p.merchant_id,
                amount_paise=p.amount_paise,
                preferred_rail=p.preferred_rail,
                issuer=p.issuer,
                created_at=p.created_at,
                is_recurring=p.is_recurring,
            )
            for p in self._template
        ]
        by_id = {p.payment_id: p for p in payments}
        ledger: list[LedgerEntry] = []

        # Event queue of (minute, sequence, payment_id, kind). The sequence
        # number keeps ordering deterministic when two events share a minute.
        queue: list[tuple[int, int, str, str]] = []
        counter = [0]

        def schedule(at: Minute, payment_id: str, kind: str) -> None:
            heapq.heappush(queue, (at, counter[0], payment_id, kind))
            counter[0] += 1

        for p in payments:
            schedule(p.created_at, p.payment_id, "attempt")

        ttl = cfg.payment_ttl_days * MINUTES_PER_DAY
        horizon = cfg.horizon_minutes

        while queue:
            now, _, pid, kind = heapq.heappop(queue)
            if now > horizon:
                break
            payment = by_id[pid]
            if not payment.is_open:
                continue
            if payment.age(now) > ttl:
                payment.abandoned_at = now
                continue

            if kind in ("attempt", "customer_return"):
                # A customer_return is an ordinary authorisation attempt that
                # happens to have been prompted by a nudge. It is resolved
                # through exactly the same gates -- which is the point. A
                # reminder brings someone back to the checkout; it does not
                # put money in their account, and it cannot revive a dead card.
                self._execute_attempt(payment, payment.preferred_rail, now,
                                      policy, ledger, collect_ledger)
                if payment.is_open:
                    schedule(now + 1, pid, "decide")

            elif kind == "decide":
                action = policy.decide(payment, now, self._context(now))
                nxt = self._apply(payment, action, now, policy, ledger,
                                  collect_ledger, schedule)
                if payment.is_open and nxt is not None and nxt <= horizon:
                    schedule(nxt, pid, "decide")

        for p in payments:
            if p.is_open:
                p.abandoned_at = horizon

        return SimulationResult(
            policy_name=getattr(policy, "name", type(policy).__name__),
            config=cfg,
            payments=payments,
            ledger=ledger,
            issuer_downtime=self.issuers.total_downtime(),
        )

    def _context(self, now: Minute) -> "PolicyContext":
        return PolicyContext(now=now, world=self)

    def _execute_attempt(
        self, payment: Payment, rail: Rail, now: Minute, policy,
        ledger: list[LedgerEntry], collect: bool,
    ) -> None:
        attempt_no = len(payment.attempts)
        ok, cause = self.resolve_attempt(payment, rail, now, attempt_no)

        from kintsugi.taxonomy.codes import raw_error_for
        raw = None if ok else raw_error_for(cause, rail, self.seed,
                                            payment.payment_id, attempt_no)

        attempt = Attempt(
            attempt_no=attempt_no, at=now, rail=rail, succeeded=ok,
            raw_error=raw, failure_class=cause,
        )
        payment.attempts.append(attempt)

        if ok:
            payment.recovered_at = now
        else:
            # A customer-visible failed retry costs goodwill, not just money.
            if attempt_no > 0 and rail.requires_customer_present:
                cust = self.population.get(payment.customer_id)
                cust.consume_patience(cal.FAILED_ATTEMPT_ATTENTION_COST.v)

        if hasattr(policy, "observe"):
            policy.observe(payment, attempt, now)

        if collect:
            ledger.append(LedgerEntry(
                at=now, payment_id=payment.payment_id,
                action=ActionKind.RETRY if attempt_no > 0 else ActionKind.WAIT,
                rail=rail, channel=None,
                rationale="initial authorisation" if attempt_no == 0 else "",
                expected_value_paise=0.0,
                outcome="success" if ok else cause.name,
                cost_paise=cal.RETRY_ATTEMPT_COST_PAISE.v if attempt_no > 0 else 0,
            ))

    def _apply(
        self, payment: Payment, action: Action, now: Minute, policy,
        ledger: list[LedgerEntry], collect: bool, schedule,
    ) -> Minute | None:
        """Execute one policy action. Returns when to next consult the policy."""
        cust = self.population.get(payment.customer_id)

        if action.kind is ActionKind.ABANDON:
            payment.abandoned_at = now
            self._log(ledger, collect, now, payment, action, "abandoned", 0)
            return None

        if action.kind is ActionKind.WAIT:
            return now + action.recheck_in

        if action.kind is ActionKind.RETRY:
            if len(payment.attempts) >= self.cfg.max_attempts:
                payment.abandoned_at = now
                return None
            rail = action.rail or payment.preferred_rail
            before = payment.is_recovered
            self._execute_attempt(payment, rail, now, policy, ledger, collect)
            if payment.is_recovered and not before:
                return None
            return now + action.recheck_in

        if action.kind is ActionKind.NUDGE:
            channel = action.channel or Channel.SMS
            nudge_index = payment.nudge_count
            payment.nudges.append(Nudge(
                at=now, channel=channel,
                template_id=f"{payment.last_failure_class.name if payment.last_failure_class else 'GENERIC'}",
                cost_paise=channel.cost_paise,
            ))
            cust.consume_patience(channel.attention_cost)

            # Did over-contact drive them away?
            hazard = cust.churn_hazard()
            if hazard > 0 and bernoulli(
                hazard, self.seed, "churn", payment.payment_id, nudge_index
            ):
                cust.churned = True
                payment.abandoned_at = now
                self._log(ledger, collect, now, payment, action,
                          "churned", channel.cost_paise)
                return None

            # A nudge buys *attention*, never money. If it lands, the customer
            # comes back and tries to pay -- and that attempt is resolved
            # through the ordinary gates, so it still fails if the balance is
            # short or the card is dead. This is the difference between a
            # reminder and a miracle, and modelling it the other way is what
            # makes naive dunning look far better than it is.
            p_respond = cust.p_nudge_converts(now, channel, nudge_index)
            responded = bernoulli(
                p_respond, self.seed, "nudge", payment.payment_id, nudge_index)
            self._log(ledger, collect, now, payment, action,
                      "responded" if responded else "ignored", channel.cost_paise)

            if responded:
                # People do not come back instantly; they return within a few
                # hours, which may itself move them past a payday boundary.
                delay = 30 + int(uniform(
                    self.seed, "nudge_delay", payment.payment_id, nudge_index
                ) * 240)
                schedule(now + delay, payment.payment_id, "customer_return")
                return None
            return now + action.recheck_in

        return now + 60

    @staticmethod
    def _log(ledger, collect, now, payment, action, outcome, cost) -> None:
        if not collect:
            return
        ledger.append(LedgerEntry(
            at=now, payment_id=payment.payment_id, action=action.kind,
            rail=action.rail, channel=action.channel,
            rationale=action.rationale,
            expected_value_paise=action.expected_value_paise,
            outcome=outcome, cost_paise=cost,
        ))


@dataclass(slots=True)
class PolicyContext:
    """What the agent is allowed to see when deciding.

    Deliberately thin. It exposes the clock and nothing about latent state --
    no issuer health, no customer balance. A policy wanting to know whether an
    issuer is down has to infer it from the attempt stream, exactly as a real
    system must. See :mod:`kintsugi.agent.health_monitor`.
    """

    now: Minute
    world: World = field(repr=False)

    @property
    def hour_of_day(self) -> int:
        return (self.now // 60) % 24

    @property
    def day_of_month(self) -> int:
        return (self.now // MINUTES_PER_DAY) % 30


# Checkout rail mix: UPI dominant, as it is in India.
_CHECKOUT_RAIL_MIX = {
    Rail.UPI_INTENT: 0.52,
    Rail.UPI_COLLECT: 0.12,
    Rail.CARD: 0.22,
    Rail.NETBANKING: 0.09,
    Rail.WALLET: 0.05,
}

#: How likely an attempt is to fail on infrastructure, by issuer health state.
#: Multiplied by the fitted ISSUER_DOWN scale. The healthy row is not zero --
#: banks decline a small fraction technically even on a good day, which is the
#: ~0.8% system-wide technical decline NPCI reports.
_INFRA_FAIL_PROB = {
    HealthState.HEALTHY: 1.0,
    HealthState.DEGRADED: 18.0,
    HealthState.OUTAGE: 75.0,
}

#: Customer-initiated checkout carries a selection effect: choosing to pay now
#: is itself evidence of having the money. Applied as a fractional lift toward
#: full liquidity. Recurring debits get none of it -- they fire on a calendar.
_FITTED_CACHE: tuple | None = None


def _load_fitted_once():
    """Load committed fitted parameters once per process."""
    global _FITTED_CACHE
    if _FITTED_CACHE is None:
        from kintsugi.world.fitting import load_fitted
        try:
            _FITTED_CACHE = load_fitted()
        except Exception:
            _FITTED_CACHE = (None, None)
    return _FITTED_CACHE


#: Fitted; see kintsugi.world.fitting. Value here is only the fit's starting
#: point -- the committed value in data/fitted_scales.json is what runs.
_CHECKOUT_SELECTION_BONUS = 0.62

#: The remaining gap between checkout and mandate authorisation is carried by
#: the per-segment fitted scales rather than by explicit penalty constants.

#: Starting hazard scales, refined by the fitting pass. These are not the
#: numbers the model ships with -- fitting overwrites them -- but they set the
#: scale so the fit converges quickly.
DEFAULT_HAZARD_SCALES: dict[FailureClass, float] = {
    FailureClass.ACCOUNT_CLOSED: 0.0018,
    FailureClass.CARD_BLOCKED: 0.0035,
    FailureClass.INVALID_INSTRUMENT: 0.0025,
    FailureClass.MANDATE_REVOKED: 0.0090,
    FailureClass.ISSUER_DOWN: 0.0120,
    FailureClass.PSP_TIMEOUT: 0.0035,
    FailureClass.NETWORK_TIMEOUT: 0.0028,
    FailureClass.INSUFFICIENT_FUNDS: 0.0850,
    FailureClass.LIMIT_EXCEEDED: 0.0060,
    FailureClass.RISK_DECLINE: 0.0090,
    FailureClass.AUTH_ABANDONED: 0.0180,
    FailureClass.AUTH_TIMEOUT: 0.0090,
    FailureClass.USER_CANCELLED: 0.0050,
}
