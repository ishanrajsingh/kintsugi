"""Calibration constants, each carrying its own provenance.

There's no public dataset of payment *failures* -- issuers and PSPs don't
publish transaction-level decline data. So any honest project here has to
simulate, and the only defensible way to simulate is to calibrate against the
aggregate statistics that are public, then be clear about which numbers came
from a source and which are ours.

Every constant is wrapped in Sourced, recording whether it's PUBLISHED
(traceable to a named source), DERIVED (arithmetic on published numbers), or
ASSUMPTION (a modelling choice). provenance_table() emits that into the
evaluation report so a reader can audit how much of the model is evidence and
how much is us.

Assumptions aren't a defect to hide -- they're a surface to expose and then
stress with the sweep in kintsugi.eval.sensitivity. A result that only holds at
one setting of an assumed constant isn't a result.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import Enum
from typing import Generic, TypeVar

from kintsugi.domain import FailureClass, Rail

T = TypeVar("T")


class Provenance(Enum):
    PUBLISHED = "published"
    DERIVED = "derived"
    ASSUMPTION = "assumption"


@dataclass(frozen=True, slots=True)
class Sourced(Generic[T]):
    """A calibration value that knows where it came from."""

    value: T
    provenance: Provenance
    source: str
    note: str = ""

    @property
    def v(self) -> T:
        return self.value

    def __float__(self) -> float:
        return float(self.value)  # type: ignore[arg-type]


def published(value: T, source: str, note: str = "") -> Sourced[T]:
    return Sourced(value, Provenance.PUBLISHED, source, note)


def derived(value: T, source: str, note: str = "") -> Sourced[T]:
    return Sourced(value, Provenance.DERIVED, source, note)


def assumed(value: T, rationale: str, note: str = "") -> Sourced[T]:
    return Sourced(value, Provenance.ASSUMPTION, rationale, note)


# ===========================================================================
# Sources
# ===========================================================================

NPCI_STATS = "NPCI, UPI Ecosystem Statistics (BD/TD & Uptime), npci.org.in"
NPCI_OC149 = "NPCI circular OC-149 (Jun 2022): banks must hold TD below 1%"
ASBE_2024 = (
    "D. Asbe (MD & CEO, NPCI), 11th SBI Banking & Economics Conclave, "
    "19 Nov 2024: 'TD reduced to 0.7-0.8% from 8-10% in 2016'"
)
BS_DECLINES = (
    "Business Standard, 'Insufficient balance, wrong PIN top reasons for "
    "failed digital transactions' (Dec 2021)"
)
RZP_PSR = "Razorpay, 'Payment Success Rate Optimization India' (2026 guide)"


# ===========================================================================
# System-wide decline structure
# ===========================================================================

TECHNICAL_DECLINE_RATE = published(
    0.008, ASBE_2024,
    "Infrastructure-caused declines (issuer/NPCI side). Regulatory ceiling 1%.",
)

BUSINESS_DECLINE_RATE = published(
    0.076, BS_DECLINES,
    "Customer-caused declines: insufficient balance, wrong PIN, do-not-honour.",
)

BD_SHARE_OF_FAILURES = published(
    0.817, BS_DECLINES,
    "Of all failed transactions, ~81.7% business decline / ~18.3% technical.",
)


# ===========================================================================
# Per-rail baseline success, healthy conditions
#
# Razorpay publishes target success-rate *bands*; we take the mid-point of each
# band as the healthy-state baseline. The simulator degrades these downward
# during issuer incidents -- it never exceeds them.
# ===========================================================================

BASE_SUCCESS_RATE: dict[Rail, Sourced[float]] = {
    Rail.UPI_INTENT: published(
        0.93, RZP_PSR, "UPI target band 90-95%; falls to 80-85% under load."),
    Rail.UPI_COLLECT: derived(
        0.86, RZP_PSR,
        "UPI band minus collect-request abandonment: the payer must open an "
        "app they did not initiate from, so drop-off is structurally higher."),
    Rail.CARD: published(
        0.90, RZP_PSR, "Domestic card target band 85-95%."),
    Rail.NETBANKING: assumed(
        0.85,
        "Razorpay routes high-value away from netbanking toward UPI/card for "
        "success, implying netbanking sits below both. Set just under the card "
        "band floor.",
    ),
    Rail.WALLET: assumed(
        0.95,
        "Closed-loop, pre-funded, no issuer in the path: the highest-success "
        "rail available. Set at the top of the observed range.",
    ),
}

# The single most important number in this project.
RECURRING_MANDATE_SUCCESS_RATE = published(
    0.40, RZP_PSR,
    "UPI Autopay success 'frequently sits at just 30-50%'. Recurring "
    "collection is the worst-performing segment in Indian payments and "
    "therefore the segment with the most recoverable value.",
)


# ===========================================================================
# Failure-cause mixes, conditional on having failed
#
# Each mix sums to 1.0 and preserves the published ~82/18 business-to-technical
# split. The split *between* business causes is an assumption informed by the
# published ranking (insufficient balance and PIN/auth problems lead), because
# no source publishes the full breakdown.
# ===========================================================================

_UPI_MIX = {
    FailureClass.INSUFFICIENT_FUNDS: 0.32,
    FailureClass.AUTH_ABANDONED: 0.20,
    FailureClass.AUTH_TIMEOUT: 0.10,
    FailureClass.RISK_DECLINE: 0.10,
    FailureClass.USER_CANCELLED: 0.06,
    FailureClass.LIMIT_EXCEEDED: 0.03,
    FailureClass.INVALID_INSTRUMENT: 0.01,
    # --- technical, 18% ---
    FailureClass.ISSUER_DOWN: 0.09,
    FailureClass.PSP_TIMEOUT: 0.05,
    FailureClass.NETWORK_TIMEOUT: 0.04,
}

_CARD_MIX = {
    FailureClass.INSUFFICIENT_FUNDS: 0.22,
    FailureClass.AUTH_ABANDONED: 0.24,   # 3DS/OTP drop-off is severe on cards
    FailureClass.AUTH_TIMEOUT: 0.10,
    FailureClass.RISK_DECLINE: 0.14,     # issuer risk engines bite harder here
    FailureClass.CARD_BLOCKED: 0.06,
    FailureClass.INVALID_INSTRUMENT: 0.04,
    FailureClass.LIMIT_EXCEEDED: 0.03,
    FailureClass.USER_CANCELLED: 0.03,
    # --- technical, 14% ---
    FailureClass.ISSUER_DOWN: 0.08,
    FailureClass.PSP_TIMEOUT: 0.04,
    FailureClass.NETWORK_TIMEOUT: 0.02,
}

_NETBANKING_MIX = {
    FailureClass.AUTH_ABANDONED: 0.30,   # long redirect journey, heavy drop-off
    FailureClass.INSUFFICIENT_FUNDS: 0.18,
    FailureClass.AUTH_TIMEOUT: 0.12,
    FailureClass.RISK_DECLINE: 0.06,
    FailureClass.USER_CANCELLED: 0.06,
    # --- technical, 28%: bank-hosted pages fail more often ---
    FailureClass.ISSUER_DOWN: 0.18,
    FailureClass.PSP_TIMEOUT: 0.06,
    FailureClass.NETWORK_TIMEOUT: 0.04,
}

# Server-initiated debits have no customer in the loop, so no AUTH_* causes
# appear at all -- nobody is present to abandon. Failure collapses onto
# balance, mandate validity and issuer health.
_MANDATE_MIX = {
    FailureClass.INSUFFICIENT_FUNDS: 0.55,
    FailureClass.MANDATE_REVOKED: 0.10,
    FailureClass.LIMIT_EXCEEDED: 0.08,
    FailureClass.RISK_DECLINE: 0.08,
    FailureClass.ACCOUNT_CLOSED: 0.03,
    FailureClass.CARD_BLOCKED: 0.02,
    # --- technical, 14% ---
    FailureClass.ISSUER_DOWN: 0.09,
    FailureClass.PSP_TIMEOUT: 0.03,
    FailureClass.NETWORK_TIMEOUT: 0.02,
}

FAILURE_MIX: dict[Rail, Sourced[dict[FailureClass, float]]] = {
    Rail.UPI_INTENT: derived(
        _UPI_MIX, f"{BS_DECLINES}; {ASBE_2024}",
        "82/18 business-technical split held; intra-business split assumed."),
    Rail.UPI_COLLECT: derived(
        _UPI_MIX, f"{BS_DECLINES}; {ASBE_2024}",
        "Same cause mix as intent; collect differs in base rate, not causes."),
    Rail.CARD: derived(
        _CARD_MIX, f"{BS_DECLINES}; {RZP_PSR}",
        "Shifted toward 3DS abandonment and issuer risk declines."),
    Rail.NETBANKING: derived(
        _NETBANKING_MIX, f"{BS_DECLINES}; {ASBE_2024}",
        "Shifted toward abandonment and issuer downtime."),
    Rail.WALLET: derived(
        _UPI_MIX, BS_DECLINES, "Approximated by the UPI mix."),
}

MANDATE_FAILURE_MIX = derived(
    _MANDATE_MIX, f"{RZP_PSR}; {BS_DECLINES}",
    "No AUTH_* causes: server-initiated debits have no customer present.",
)


# ===========================================================================
# Issuer health dynamics
#
# Outages are the part of this model most visible in the demo and most
# consequential for routing, so the shape is stated explicitly. Durations are
# assumptions: NPCI publishes monthly uptime, not incident-level traces.
# ===========================================================================

ISSUER_OUTAGE_RATE_PER_DAY = assumed(
    0.04,
    "Implied by NPCI monthly uptime obligations: a bank meeting ~99.5% uptime "
    "experiences on the order of one multi-hour incident per month.",
)

ISSUER_OUTAGE_MEAN_MINUTES = assumed(
    95.0,
    "Reported UPI incidents typically resolve within one to three hours.",
)

NETWORK_WIDE_OUTAGE_RATE_PER_DAY = assumed(
    0.012,
    "Rate of NPCI-side events that impair every issuer at once. These are "
    "real and reported -- NPCI has attributed multi-bank UPI failures to "
    "year-end processing load -- and their absence made this world "
    "conservative in the agent's favour: with independent outages a rail or "
    "issuer switch always has somewhere healthy to go. Roughly one such event "
    "every three months.",
)

NETWORK_WIDE_OUTAGE_MEAN_MINUTES = assumed(
    55.0, "Shorter than a single-bank incident; NPCI restores centrally.")

ISSUER_DEGRADED_RATE_PER_DAY = assumed(
    0.35,
    "Partial degradation (elevated latency, intermittent declines) is far more "
    "common than hard outage and is what banks under-report.",
)

ISSUER_DEGRADED_MEAN_MINUTES = assumed(45.0, "Shorter than full outages.")

OUTAGE_SUCCESS_MULTIPLIER = published(
    0.10, RZP_PSR,
    "During a hard issuer outage almost nothing authorises on that issuer.",
)

DEGRADED_SUCCESS_MULTIPLIER = derived(
    0.87, RZP_PSR,
    "UPI 'drops to 80-85% when a major bank's servers choke at peak', against "
    "a 93% healthy baseline: 0.825/0.93 ~= 0.887, rounded down slightly.",
)


# ===========================================================================
# Customer behaviour
# ===========================================================================

SALARY_DAY_OF_MONTH = assumed(
    1, "Indian salary credit clusters at month start (1st-7th).")

SALARY_REPLENISH_WINDOW_DAYS = assumed(
    7, "Balance recovery is spread across the first week, not instantaneous.")

INTRADAY_BALANCE_REFRESH = assumed(
    0.35,
    "Probability that a customer's balance position is redrawn within the day "
    "rather than holding at the day's value. Keying the balance strictly to "
    "the calendar day makes the midnight boundary far too sharp: the "
    "simulator then reported an 82% gain from retrying at +24h instead of "
    "+2h, against a published A/B result of +6.5%. Real balances move "
    "intraday -- salary credits land mid-morning, transfers arrive, other "
    "debits clear -- so a minority of retries within the same day do face a "
    "genuinely different balance.",
)

BASE_PATIENCE = assumed(
    2.5,
    "Goodwill budget per customer in nudge-attention units. At SMS cost 0.40 "
    "this permits roughly six sends before exhaustion.",
)

CHURN_HAZARD_AT_ZERO_PATIENCE = assumed(
    0.25,
    "Probability a customer abandons the payment outright once their goodwill "
    "budget is spent. Over-nudging is modelled as genuinely destructive, not "
    "merely ineffective -- otherwise the optimal policy is to spam forever.",
)

RBI_AFA_EXEMPT_LIMIT_PAISE = published(
    1_500_000,
    "RBI e-mandate framework (limit raised to INR 15,000): recurring "
    "collections below this need no additional-factor authentication per "
    "cycle -- only the initial mandate registration does. Above it, every "
    "debit requires AFA, which puts the customer back in the loop.",
    "A higher INR 1 lakh ceiling applies to insurance premiums, mutual-fund "
    "SIPs and credit-card bills; those categories are not modelled separately "
    "here, so this is the conservative single threshold.",
)

PRE_DEBIT_NOTICE_ATTENTION_COST = assumed(
    0.25,
    "Goodwill consumed by the pre-debit notification RBI requires at least 24 "
    "hours before every mandate debit. It is mandatory, not a choice, but it "
    "is still a message: a customer on three subscriptions is already being "
    "contacted three times a cycle before any recovery messaging begins. "
    "Ignoring it would let the agent believe it has a fresh attention budget "
    "it does not have. Priced just above an SMS reminder, since it is "
    "expected and therefore less irritating.",
)

ACCOUNT_UPDATER_HIT_RATE = assumed(
    0.30,
    "Probability that a card-network account updater supplies refreshed "
    "credentials for a dead card, per retry, with no customer involvement. "
    "Visa and Mastercard updaters are reported to recover 3-5% of recurring "
    "revenue and lift recurring authorisation by 5-10 points. Unlike the "
    "customer-asked path this is automatic, so it applies identically to every "
    "policy and raises all of them -- it adds realism, not differentiation. "
    "Card rails only: UPI has no equivalent service.",
)

CREDENTIAL_UPDATE_SUCCESS = assumed(
    0.55,
    "Probability that a customer who responds to a 'your card is no longer "
    "usable, please update it' message actually supplies working new details. "
    "A dead instrument is permanently dead, but the *customer* is not: "
    "documented industry practice for a hard decline is not to retry but to "
    "send a credential-update request, and account-updater services alone "
    "recover 3-5% of recurring revenue. Treating terminal causes as an "
    "immediate write-off ignores the one action that does work on them. "
    "Note this models the *customer-asked* path only: automatic account "
    "updaters, where the network pushes refreshed credentials with no customer "
    "involvement, are not modelled, since they are identical across policies "
    "and would raise every number without changing any comparison.",
)

NUDGE_CONVERSION_BASE = assumed(
    0.22,
    "Probability a customer-present failure converts after one well-timed "
    "nudge. Deliberately conservative: dunning literature reports wide ranges "
    "and we would rather understate the gain our own agent produces.",
)

NUDGE_DECAY = assumed(
    0.55, "Each successive nudge is ~45% less effective than the last.")


# ===========================================================================
# Economics
# ===========================================================================

RETRY_ATTEMPT_COST_PAISE = assumed(
    15,
    "A failed attempt is not free: it consumes issuer trust, PSP quota and "
    "customer patience. Priced as a small explicit cost so the policy cannot "
    "retry infinitely without penalty.",
)

FAILED_ATTEMPT_ATTENTION_COST = assumed(
    0.10,
    "A customer-visible failed retry irritates roughly a quarter as much as "
    "an SMS.",
)


# ===========================================================================
# Provenance reporting
# ===========================================================================

def provenance_table() -> list[dict[str, str]]:
    """Every calibration constant with its provenance, for the report.

    Judges should not have to read the source to find out which numbers we
    made up. This renders that table mechanically.
    """
    module = sys.modules[__name__]
    rows: list[dict[str, str]] = []
    for name in sorted(dir(module)):
        if name.startswith("_"):
            continue
        obj = getattr(module, name)
        if isinstance(obj, Sourced):
            rows.append(_row(name, obj))
        elif isinstance(obj, dict):
            for key, val in obj.items():
                if isinstance(val, Sourced):
                    label = getattr(key, "name", str(key))
                    rows.append(_row(f"{name}[{label}]", val))
    return rows


def _row(name: str, s: Sourced) -> dict[str, str]:
    value = s.value
    if isinstance(value, dict):
        rendered = f"<{len(value)} causes>"
    elif isinstance(value, float):
        rendered = f"{value:g}"
    else:
        rendered = str(value)
    return {
        "constant": name,
        "value": rendered,
        "provenance": s.provenance.value,
        "source": s.source,
        "note": s.note,
    }


def provenance_summary() -> dict[str, int]:
    """Counts by provenance kind -- the headline honesty metric."""
    counts = {p.value: 0 for p in Provenance}
    for row in provenance_table():
        counts[row["provenance"]] += 1
    return counts
