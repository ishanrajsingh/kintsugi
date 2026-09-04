"""Core domain types for payment failure recovery.

Three conventions worth knowing before reading anything else:

Money is integer paise, never floats -- a recovery engine that reports revenue
in floats eventually reports revenue that doesn't reconcile. Time is integer
minutes since the start of the horizon, which keeps runs bit-for-bit
reproducible (the eval harness depends on that). And the failure taxonomy is
organised by *disposition* -- the kind of intervention that could work -- rather
than by error text, because that's the only grouping a policy can act on.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

Paise = int
Minute = int


class Rail(Enum):
    """A distinct path to money movement.

    Rails matter because "retry on a different rail" is a real recovery action
    with a genuinely different success profile: a UPI collect request failing
    because the payer never opened the app tells you nothing about whether that
    customer's debit card would work.
    """

    UPI_COLLECT = auto()
    UPI_INTENT = auto()
    CARD = auto()
    NETBANKING = auto()
    WALLET = auto()

    @property
    def requires_customer_present(self) -> bool:
        """True if the rail cannot complete without live customer action.

        This is the single most important structural fact in retry logic: a
        server-side retry is only meaningful on rails that can complete without
        a human. Retrying a UPI collect at 3am is theatre.
        """
        return self in {Rail.UPI_COLLECT, Rail.UPI_INTENT, Rail.NETBANKING}

    @property
    def server_can_reprompt(self) -> bool:
        """True if the merchant can put a fresh prompt in front of the payer
        without the payer coming back first.

        This is a different question from ``requires_customer_present``, and
        conflating the two badly distorts what recovery actions are available.
        A UPI *collect* request is merchant-initiated: retrying pushes a new
        approval request into the payer's app, so a retry genuinely re-prompts.
        A UPI *intent* payment is payer-initiated -- they tapped Pay and were
        deep-linked out -- and netbanking is a redirect the payer drives. For
        those, no server-side retry reaches anyone; the only way back is to
        send the customer a message.

        Modelling every customer-present rail as re-promptable made outbound
        messaging vestigial: retries were strictly cheaper reminders, and the
        agent's best configuration sent zero messages. That is an artefact of
        the abstraction, not a finding about payments.
        """
        return self is Rail.UPI_COLLECT


class Disposition(Enum):
    """What *category* of intervention could plausibly recover this failure."""

    TERMINAL = auto()
    """The instrument is dead. No retry, no nudge, ever. Recovery requires a
    new instrument from the customer."""

    TIME_HEALS = auto()
    """The customer is willing and the instrument is valid; some external state
    (balance, daily limit) needs to change. Retry later, on a cadence matched
    to how that state actually resolves."""

    RAIL_SWITCH = auto()
    """This path is impaired but the customer is reachable another way. Retry
    soon, on a different rail."""

    NEEDS_CUSTOMER = auto()
    """No server-side retry can succeed. Requires a human to come back and
    authenticate. Nudge, don't hammer."""

    UNKNOWN = auto()
    """Unmapped error. Treated conservatively and surfaced for taxonomy review;
    see :mod:`kintsugi.taxonomy`."""


class FailureClass(Enum):
    """Canonical failure causes, normalised from messy gateway error strings."""

    # --- Terminal -------------------------------------------------------
    ACCOUNT_CLOSED = auto()
    CARD_BLOCKED = auto()
    INVALID_INSTRUMENT = auto()
    MANDATE_REVOKED = auto()

    # --- Time heals -----------------------------------------------------
    INSUFFICIENT_FUNDS = auto()
    LIMIT_EXCEEDED = auto()

    # --- Rail switch ----------------------------------------------------
    RISK_DECLINE = auto()
    ISSUER_DOWN = auto()
    PSP_TIMEOUT = auto()
    NETWORK_TIMEOUT = auto()

    # --- Needs customer -------------------------------------------------
    AUTH_ABANDONED = auto()
    AUTH_TIMEOUT = auto()
    USER_CANCELLED = auto()

    UNKNOWN = auto()

    @property
    def disposition(self) -> Disposition:
        return _DISPOSITION[self]

    @property
    def is_terminal(self) -> bool:
        return self.disposition is Disposition.TERMINAL


_DISPOSITION: dict[FailureClass, Disposition] = {
    FailureClass.ACCOUNT_CLOSED: Disposition.TERMINAL,
    FailureClass.CARD_BLOCKED: Disposition.TERMINAL,
    FailureClass.INVALID_INSTRUMENT: Disposition.TERMINAL,
    FailureClass.MANDATE_REVOKED: Disposition.TERMINAL,
    FailureClass.INSUFFICIENT_FUNDS: Disposition.TIME_HEALS,
    FailureClass.LIMIT_EXCEEDED: Disposition.TIME_HEALS,
    FailureClass.RISK_DECLINE: Disposition.RAIL_SWITCH,
    FailureClass.ISSUER_DOWN: Disposition.RAIL_SWITCH,
    FailureClass.PSP_TIMEOUT: Disposition.RAIL_SWITCH,
    FailureClass.NETWORK_TIMEOUT: Disposition.RAIL_SWITCH,
    FailureClass.AUTH_ABANDONED: Disposition.NEEDS_CUSTOMER,
    FailureClass.AUTH_TIMEOUT: Disposition.NEEDS_CUSTOMER,
    FailureClass.USER_CANCELLED: Disposition.NEEDS_CUSTOMER,
    FailureClass.UNKNOWN: Disposition.UNKNOWN,
}


class Channel(Enum):
    """Outbound contact channels, cheapest first."""

    EMAIL = auto()
    SMS = auto()
    WHATSAPP = auto()

    @property
    def cost_paise(self) -> Paise:
        """Marginal send cost. Indicative Indian A2P rates, 2025-26."""
        return _CHANNEL_COST[self]

    @property
    def attention_cost(self) -> float:
        """How much of the customer's goodwill a single send consumes.

        Denominated in the same units as :attr:`CustomerState.patience` so the
        policy can trade rupees against irritation on one scale.
        """
        return _CHANNEL_ATTENTION[self]


_CHANNEL_COST: dict[Channel, Paise] = {
    Channel.EMAIL: 2,       # ~INR 0.02
    Channel.SMS: 20,        # ~INR 0.20
    Channel.WHATSAPP: 35,   # ~INR 0.35 utility-template
}

_CHANNEL_ATTENTION: dict[Channel, float] = {
    Channel.EMAIL: 0.15,
    Channel.SMS: 0.40,
    Channel.WHATSAPP: 0.55,
}


# ---------------------------------------------------------------------------
# Observable records
#
# Everything below is what a real payments stack would persist. The policy is
# only ever handed these types -- never the simulator's latent state. That
# boundary is enforced in kintsugi.world.simulator and is what makes the
# evaluation honest rather than circular.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Attempt:
    """One authorisation attempt against one rail."""

    attempt_no: int
    at: Minute
    rail: Rail
    succeeded: bool
    raw_error: str | None = None
    failure_class: FailureClass | None = None
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class Nudge:
    """One outbound message asking the customer to complete payment."""

    at: Minute
    channel: Channel
    template_id: str
    cost_paise: Paise


@dataclass(slots=True)
class Payment:
    """A payment obligation and its full recovery history.

    A ``Payment`` is *not* a transaction attempt -- it is the merchant's claim
    on money, which may survive many failed attempts. Modelling it this way is
    what lets the agent reason about lifetime recovery value instead of
    treating each retry as an isolated event.
    """

    payment_id: str
    customer_id: str
    merchant_id: str
    amount_paise: Paise
    preferred_rail: Rail
    issuer: str
    created_at: Minute
    is_recurring: bool = False
    """True for scheduled mandate debits. Observable: a merchant always knows
    whether a charge is a subscription renewal or a customer at a checkout."""

    attempts: list[Attempt] = field(default_factory=list)
    nudges: list[Nudge] = field(default_factory=list)
    recovered_at: Minute | None = None
    abandoned_at: Minute | None = None
    credentials_updated: bool = False
    """True once the customer has supplied a working replacement instrument.

    A dead card stays dead; this records that the *payment* is now sitting on
    a different one. It is the only thing that makes a terminal cause
    recoverable, and it only ever happens because the customer was asked."""

    # -- derived ---------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self.recovered_at is None and self.abandoned_at is None

    @property
    def is_recovered(self) -> bool:
        return self.recovered_at is not None

    @property
    def last_attempt(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None

    @property
    def last_failure_class(self) -> FailureClass | None:
        last = self.last_attempt
        if last is None or last.succeeded:
            return None
        return last.failure_class

    @property
    def retry_count(self) -> int:
        """Attempts beyond the original authorisation."""
        return max(0, len(self.attempts) - 1)

    @property
    def nudge_count(self) -> int:
        return len(self.nudges)

    @property
    def nudge_cost_paise(self) -> Paise:
        return sum(n.cost_paise for n in self.nudges)

    def minutes_since_last_attempt(self, now: Minute) -> Minute:
        last = self.last_attempt
        return now - (last.at if last else self.created_at)

    def minutes_since_last_nudge(self, now: Minute) -> Minute:
        """Contact spacing is a different clock from retry backoff.

        Measuring reminder spacing against the last *attempt* conflates the two
        and produces contact schedules that drift whenever a retry happens.
        """
        if not self.nudges:
            return now - self.created_at
        return now - self.nudges[-1].at

    def age(self, now: Minute) -> Minute:
        return now - self.created_at


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


class ActionKind(Enum):
    WAIT = auto()
    RETRY = auto()
    NUDGE = auto()
    ABANDON = auto()


@dataclass(frozen=True, slots=True)
class Action:
    """A decision the recovery agent makes about one open payment.

    Actions carry a ``rationale`` because a recovery engine that cannot explain
    why it did not chase a large payment is not deployable at a merchant. The
    rationale is written to the decision log and is what the merchant-facing
    explanation surface reads back.
    """

    kind: ActionKind
    rail: Rail | None = None
    channel: Channel | None = None
    rationale: str = ""
    expected_value_paise: float = 0.0
    recheck_in: Minute = 60
    """For WAIT: how long before the agent should reconsider this payment.

    Carrying the interval on the action lets the simulator schedule decisions
    instead of polling every open payment on every tick. It is also the honest
    representation of what a real recovery worker does -- it sets a timer.
    """

    @staticmethod
    def wait(recheck_in: Minute = 60, rationale: str = "", ev: float = 0.0) -> Action:
        return Action(ActionKind.WAIT, rationale=rationale,
                      expected_value_paise=ev, recheck_in=max(1, recheck_in))

    @staticmethod
    def retry(rail: Rail, rationale: str = "", ev: float = 0.0) -> Action:
        return Action(ActionKind.RETRY, rail=rail, rationale=rationale,
                      expected_value_paise=ev)

    @staticmethod
    def nudge(channel: Channel, rationale: str = "", ev: float = 0.0) -> Action:
        return Action(ActionKind.NUDGE, channel=channel, rationale=rationale,
                      expected_value_paise=ev)

    @staticmethod
    def abandon(rationale: str = "") -> Action:
        return Action(ActionKind.ABANDON, rationale=rationale)
