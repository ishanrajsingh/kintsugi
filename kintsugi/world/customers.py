"""Latent customer state: liquidity, attention, and patience.

These three mechanisms are what make recovery a *decision* problem rather than
a retry loop, because each one gives a well-timed action a genuinely higher
success probability than a badly-timed one:

* **Liquidity** follows the salary cycle. An ``INSUFFICIENT_FUNDS`` failure on
  the 28th and the same failure on the 2nd are not the same event, and a policy
  that knows the difference recovers money a fixed-interval retry loop burns.
* **Attention** varies by hour. A nudge at 3am is a wasted send and a small
  amount of goodwill spent for nothing.
* **Patience** is finite and destructible. Over-nudging does not merely stop
  working; it makes the customer abandon. Without this, the optimal policy is
  to message forever, which is both wrong and the thing real dunning systems
  actually get wrong.

None of this is visible to the policy. The policy sees error codes and
timestamps, exactly as a production stack would.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import exp

from kintsugi import calibration as cal
from kintsugi.domain import Channel, Minute, Paise
from kintsugi.rng import uniform

MINUTES_PER_DAY = 1440
DAYS_PER_MONTH = 30


@dataclass(slots=True)
class Customer:
    """One payer, with latent financial and behavioural state."""

    customer_id: str
    issuer_code: str
    liquidity_base: float
    """Baseline probability of covering a typical payment, before salary
    effects. Low values are genuinely cash-tight customers."""

    salary_day: int
    """Day of month the customer's balance replenishes."""

    typical_amount_paise: Paise
    peak_hour: int
    """Local hour at which this customer is most responsive to a nudge."""

    patience: float = field(default_factory=lambda: cal.BASE_PATIENCE.v)
    """Remaining goodwill budget. Consumed by nudges and failed retries."""

    churned: bool = False

    # -- liquidity -------------------------------------------------------

    def liquidity_at(self, minute: Minute) -> float:
        """Probability of covering a typical payment at this instant.

        Rises on salary day and decays across the month. The decay constant is
        set so a customer is meaningfully tighter in the last week than the
        first -- the pattern any collections team in India will describe.
        """
        day_of_month = (minute // MINUTES_PER_DAY) % DAYS_PER_MONTH
        days_since_salary = (day_of_month - self.salary_day) % DAYS_PER_MONTH
        window = cal.SALARY_REPLENISH_WINDOW_DAYS.v
        boost = (1.0 - self.liquidity_base) * exp(-days_since_salary / window)
        return min(1.0, self.liquidity_base + boost)

    def p_insufficient(
        self,
        minute: Minute,
        amount: Paise,
        scale: float,
        selection_bonus: float = 0.0,
    ) -> float:
        """Probability the balance does *not* cover this amount, now.

        Two properties matter more than the exact functional form.

        **Heterogeneity, not a common rate.** The squared term spreads the
        population hard: a comfortable customer is short well under 1% of the
        time, a genuinely cash-tight one more than half the time. This is what
        makes recovery a prediction problem at all. If everyone shared one 3%
        chance of bouncing, then conditional on a failure a retry would almost
        always succeed, and there would be nothing to be clever about. Because
        the population is spread, a payment that just failed on balance is
        strong evidence the payer is in the tail -- and will fail again
        tomorrow. Persistence is produced by *who the customer is*, not by any
        explicit autocorrelation term.

        **Selection.** ``selection_bonus`` raises effective liquidity for
        customer-initiated checkout. Someone who has just chosen to pay has
        thereby revealed they believe they have the money; a recurring debit
        fires on a calendar date and reveals nothing. That single asymmetry is
        the honest mechanism behind UPI Autopay authorising in the 30-50% band
        while checkout on the same rail clears above 90%, and it is why the
        model does not need a large unexplained penalty bolted onto mandates.
        """
        liq = self.liquidity_at(minute)
        liq_eff = liq + selection_bonus * (1.0 - liq)
        pressure = amount / max(1, self.typical_amount_paise * 2)
        shortfall = max(0.0, 1.0 - liq_eff) ** 2
        return max(0.0, min(0.98, scale * shortfall * (1.0 + pressure)))

    def p_funds_available(
        self, minute: Minute, amount: Paise, scale: float,
        selection_bonus: float = 0.0,
    ) -> float:
        return 1.0 - self.p_insufficient(minute, amount, scale, selection_bonus)

    # -- attention -------------------------------------------------------

    def attention_at(self, minute: Minute) -> float:
        """Responsiveness multiplier in [0, 1] for the given instant.

        A raised cosine centred on the customer's peak hour: high in their
        active window, near zero overnight.
        """
        hour = (minute // 60) % 24
        distance = min((hour - self.peak_hour) % 24, (self.peak_hour - hour) % 24)
        # distance is 0..12; map to a smooth falloff
        return max(0.05, exp(-((distance / 4.5) ** 2)))

    def p_nudge_converts(
        self, minute: Minute, channel: Channel, nudge_index: int
    ) -> float:
        """Probability a nudge brings this customer back to complete payment."""
        if self.churned:
            return 0.0
        decay = cal.NUDGE_DECAY.v ** nudge_index
        patience_factor = max(0.0, min(1.0, self.patience / cal.BASE_PATIENCE.v))
        return (
            cal.NUDGE_CONVERSION_BASE.v
            * decay
            * self.attention_at(minute)
            * _CHANNEL_REACH[channel]
            * (0.4 + 0.6 * patience_factor)
        )

    # -- patience --------------------------------------------------------

    def consume_patience(self, amount: float) -> None:
        self.patience -= amount

    def churn_hazard(self) -> float:
        """Probability of abandoning outright, given spent goodwill.

        Zero while budget remains, then rising once it is overdrawn. Modelling
        it as a cliff rather than a gradient means a policy is not punished for
        reasonable contact, only for hounding.
        """
        if self.patience >= 0:
            return 0.0
        overdraft = min(3.0, -self.patience)
        return cal.CHURN_HAZARD_AT_ZERO_PATIENCE.v * (overdraft / 3.0)


#: How reliably each channel actually reaches a person. Email is cheap because
#: nobody reads it; WhatsApp costs more because they do.
_CHANNEL_REACH: dict[Channel, float] = {
    Channel.EMAIL: 0.45,
    Channel.SMS: 0.80,
    Channel.WHATSAPP: 1.00,
}


class CustomerPopulation:
    """A deterministic population of payers for one world.

    Built entirely from keyed draws so that the same seed reproduces the same
    people, independent of what any policy later does to them.
    """

    __slots__ = ("customers", "_by_index")

    def __init__(
        self,
        size: int,
        seed: int,
        issuer_codes: list[str],
        issuer_weights: list[float],
    ) -> None:
        self.customers: dict[str, Customer] = {}
        self._by_index: list[str] = []

        cumulative: list[float] = []
        running = 0.0
        for w in issuer_weights:
            running += w
            cumulative.append(running)

        for i in range(size):
            cid = f"cust_{i:06d}"

            u_issuer = uniform(seed, "cust_issuer", i) * running
            issuer = issuer_codes[-1]
            for code, threshold in zip(issuer_codes, cumulative):
                if u_issuer < threshold:
                    issuer = code
                    break

            # Liquidity is beta-ish: most customers comfortable, a real tail of
            # cash-tight ones. Built from two uniforms to get the skew without
            # pulling in a sampler that would break key-determinism.
            u1 = uniform(seed, "liq_a", i)
            u2 = uniform(seed, "liq_b", i)
            liquidity = 0.35 + 0.6 * max(u1, u2)

            salary_day = int(uniform(seed, "salary", i) * 7)
            peak_hour = 9 + int(uniform(seed, "peak", i) * 13)  # 09:00-21:00

            # Log-uniform amounts: many small payments, a heavy tail of large
            # ones. Recovery value is concentrated in that tail, so getting its
            # shape roughly right matters more than the median.
            u_amt = uniform(seed, "amt", i)
            typical = int(20_000 * (10 ** (2.0 * u_amt)))  # INR 200 - 20,000

            customer = Customer(
                customer_id=cid,
                issuer_code=issuer,
                liquidity_base=liquidity,
                salary_day=salary_day,
                typical_amount_paise=typical,
                peak_hour=peak_hour,
            )
            self.customers[cid] = customer
            self._by_index.append(cid)

    def __len__(self) -> int:
        return len(self._by_index)

    def get(self, customer_id: str) -> Customer:
        return self.customers[customer_id]

    def by_index(self, index: int) -> Customer:
        return self.customers[self._by_index[index % len(self._by_index)]]

    def reset(self) -> None:
        """Restore mutable state so the next policy meets the same people.

        Patience and churn are the only customer attributes a policy can
        change, so they are the only ones that need resetting between runs.
        """
        for c in self.customers.values():
            c.patience = cal.BASE_PATIENCE.v
            c.churned = False
