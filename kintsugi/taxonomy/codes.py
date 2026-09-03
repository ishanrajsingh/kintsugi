"""A catalogue of realistically messy gateway decline strings.

Why this is hard in production
------------------------------
There is no single decline vocabulary in Indian payments. A card decline
arrives as an ISO 8583 response code ("51"), a UPI decline as an NPCI code
("Z9", "U30"), and every PSP and bank wraps those in its own free text -- often
truncated, sometimes misspelled, occasionally just "Payment failed". The same
underlying cause reaches you as a dozen different strings, and new variants
appear whenever a bank changes a template. A payments team that cannot map
these onto a stable taxonomy cannot build recovery logic on top of them.

That is the job this project gives the language model, and the reason the
LLM is placed here rather than in the decision loop: normalising open-ended,
drifting natural-language input is what it is genuinely better at than a rule
table, while choosing which payment to retry is not.

Held-out variants
-----------------
Templates flagged ``holdout=True`` are never shown to the rule engine and are
excluded from any rule authoring. They stand in for the strings that appear in
production *after* you ship. Classification accuracy on held-out strings is
reported separately in the evaluation, because accuracy on strings you already
wrote rules for measures nothing.

Codes below are the real ISO 8583 and NPCI response codes (checked against
published references -- an earlier draft used a fabricated ``U67`` for the
per-transaction limit, where the actual codes are ``Z8`` for amount and ``Z7``
for velocity). The wrapper text around them is representative rather than
copied from any particular provider. The final block carries Razorpay's own
published ``reason`` identifiers verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass

from kintsugi.domain import FailureClass, Rail
from kintsugi.rng import uniform


@dataclass(frozen=True, slots=True)
class ErrorTemplate:
    text: str
    holdout: bool = False
    rails: tuple[Rail, ...] | None = None
    """Rails this string can appear on. ``None`` means any."""


UPI_RAILS = (Rail.UPI_INTENT, Rail.UPI_COLLECT)
CARD_RAILS = (Rail.CARD,)


ERROR_CATALOGUE: dict[FailureClass, tuple[ErrorTemplate, ...]] = {
    FailureClass.INSUFFICIENT_FUNDS: (
        ErrorTemplate("51 - Insufficient funds", rails=CARD_RAILS),
        ErrorTemplate("Z9: Insufficient balance in remitter account", rails=UPI_RAILS),
        ErrorTemplate("BANK_DECLINED: insufficient balance"),
        ErrorTemplate("Your account does not have sufficient balance to complete this transaction"),
        ErrorTemplate("DECLINE - NSF"),
        ErrorTemplate("payment failed: low balance"),
        ErrorTemplate("Txn declined by bank (reason: balance)", holdout=True),
        ErrorTemplate("insuff_funds", holdout=True),
        ErrorTemplate("A/c balance low. Please retry after adding funds.", holdout=True),
    ),
    FailureClass.LIMIT_EXCEEDED: (
        ErrorTemplate("61 - Exceeds withdrawal amount limit", rails=CARD_RAILS),
        ErrorTemplate("Z8: Per transaction limit exceeded", rails=UPI_RAILS),
        ErrorTemplate("Z7: Too many transactions in the permitted interval",
                      rails=UPI_RAILS),
        ErrorTemplate("Daily limit for this account has been reached"),
        ErrorTemplate("TXN_LIMIT_BREACHED"),
        ErrorTemplate("65 - Exceeds withdrawal frequency limit", rails=CARD_RAILS),
        ErrorTemplate("You have crossed the permitted number of transactions for today", holdout=True),
        ErrorTemplate("velocity check failed", holdout=True),
    ),
    FailureClass.RISK_DECLINE: (
        ErrorTemplate("05 - Do not honor", rails=CARD_RAILS),
        ErrorTemplate("U16: Risk threshold exceeded", rails=UPI_RAILS),
        ErrorTemplate("Transaction declined by issuing bank"),
        ErrorTemplate("57 - Transaction not permitted to cardholder", rails=CARD_RAILS),
        ErrorTemplate("DECLINED_BY_RISK_ENGINE"),
        ErrorTemplate("Payment blocked for security reasons. Contact your bank."),
        ErrorTemplate("issuer refused authorisation, no reason supplied", holdout=True),
        ErrorTemplate("62 - Restricted card", holdout=True, rails=CARD_RAILS),
    ),
    FailureClass.ISSUER_DOWN: (
        ErrorTemplate("91 - Issuer or switch inoperative", rails=CARD_RAILS),
        ErrorTemplate("U30: Debit failed at remitter bank", rails=UPI_RAILS),
        ErrorTemplate("BT: Bank timed out"),
        ErrorTemplate("Bank server is currently unavailable. Please try later."),
        ErrorTemplate("ISSUER_UNAVAILABLE"),
        ErrorTemplate("96 - System malfunction at issuer", rails=CARD_RAILS),
        ErrorTemplate("remitter bank not responding", holdout=True),
        ErrorTemplate("upstream bank unreachable (503)", holdout=True),
    ),
    FailureClass.PSP_TIMEOUT: (
        ErrorTemplate("GATEWAY_ERROR: request timed out"),
        ErrorTemplate("PSP did not respond within the configured window"),
        ErrorTemplate("504 Gateway Timeout"),
        ErrorTemplate("payment_gateway_timeout"),
        ErrorTemplate("no response from acquirer, transaction status unknown", holdout=True),
    ),
    FailureClass.NETWORK_TIMEOUT: (
        ErrorTemplate("Network error, please try again"),
        ErrorTemplate("CONNECTION_RESET during authorisation"),
        ErrorTemplate("socket timeout while contacting switch"),
        ErrorTemplate("NPCI unreachable", rails=UPI_RAILS),
        ErrorTemplate("transient network failure at switch layer", holdout=True),
    ),
    FailureClass.AUTH_ABANDONED: (
        ErrorTemplate("ZM: Invalid or missing MPIN", rails=UPI_RAILS),
        ErrorTemplate("Customer did not complete authentication"),
        ErrorTemplate("3DS_AUTHENTICATION_ABANDONED", rails=CARD_RAILS),
        ErrorTemplate("OTP not entered by customer"),
        ErrorTemplate("User dropped off at bank page"),
        ErrorTemplate("collect request not approved by payer", rails=UPI_RAILS),
        ErrorTemplate("authentication window closed without submission", holdout=True),
        ErrorTemplate("cust_auth_incomplete", holdout=True),
    ),
    FailureClass.AUTH_TIMEOUT: (
        ErrorTemplate("U69: Collect request expired", rails=UPI_RAILS),
        ErrorTemplate("Authentication session expired"),
        ErrorTemplate("OTP expired before submission"),
        ErrorTemplate("TIMEOUT_AT_ACS", rails=CARD_RAILS),
        ErrorTemplate("payer did not act within validity period", holdout=True),
    ),
    FailureClass.USER_CANCELLED: (
        ErrorTemplate("Transaction cancelled by user"),
        ErrorTemplate("USER_ABORTED"),
        ErrorTemplate("Payer declined the collect request", rails=UPI_RAILS),
        ErrorTemplate("customer pressed back on the bank page", holdout=True),
    ),
    FailureClass.ACCOUNT_CLOSED: (
        ErrorTemplate("14 - Invalid account number", rails=CARD_RAILS),
        ErrorTemplate("Account closed or dormant"),
        ErrorTemplate("ACCOUNT_INACTIVE"),
        ErrorTemplate("Beneficiary account frozen", rails=UPI_RAILS),
        ErrorTemplate("a/c no longer operative", holdout=True),
    ),
    FailureClass.CARD_BLOCKED: (
        ErrorTemplate("41 - Lost card, pick up", rails=CARD_RAILS),
        ErrorTemplate("43 - Stolen card, pick up", rails=CARD_RAILS),
        ErrorTemplate("Card has been blocked by the issuer"),
        ErrorTemplate("CARD_BLOCKED"),
        ErrorTemplate("hotlisted instrument", holdout=True),
    ),
    FailureClass.INVALID_INSTRUMENT: (
        ErrorTemplate("54 - Expired card", rails=CARD_RAILS),
        ErrorTemplate("Invalid card number"),
        ErrorTemplate("VPA does not exist", rails=UPI_RAILS),
        ErrorTemplate("INVALID_INSTRUMENT_DETAILS"),
        ErrorTemplate("card expiry date has passed", holdout=True),
        ErrorTemplate("payee address invalid or deregistered", holdout=True),
    ),
    FailureClass.MANDATE_REVOKED: (
        ErrorTemplate("Mandate has been revoked by the payer"),
        ErrorTemplate("UMN not found or cancelled", rails=UPI_RAILS),
        ErrorTemplate("SUBSCRIPTION_CANCELLED_AT_BANK"),
        ErrorTemplate("standing instruction withdrawn by customer", holdout=True),
    ),
}


# ---------------------------------------------------------------------------
# Razorpay's own published error vocabulary
#
# Everything above is wire-level: ISO 8583 response codes, NPCI codes, and the
# free text PSPs wrap around them. This block is different -- these are the
# actual `reason` identifiers Razorpay publishes in its error documentation,
# which is what a merchant integrating against Razorpay actually receives.
#
# Two things make them worth carrying alongside the raw strings.
#
# First, authenticity: a taxonomy built only on invented strings proves nothing
# about whether it would survive contact with production. These are production.
#
# Second, Razorpay tags every error with a `source` -- customer, business,
# gateway, or razorpay -- and that field turns out to be an independent
# derivation of the same idea as this project's `Disposition`. Their `customer`
# source splits across TIME_HEALS and NEEDS_CUSTOMER depending on whether money
# or attention is missing; `gateway` maps onto RAIL_SWITCH. The agreement is
# reassuring precisely because it was arrived at separately.
#
# Deliberately excluded: `source: business` errors such as
# `payment_method_not_enabled` or `live_mode_not_enabled`. Those are merchant
# misconfiguration, not recoverable payments -- no retry, reminder or timing
# choice fixes them, and a recovery agent that treats them as its problem is
# solving the wrong one. They belong in an integration alert, not a dunning
# queue.
# ---------------------------------------------------------------------------

#: reason identifier -> (canonical class, Razorpay source, held out?)
RAZORPAY_REASONS: tuple[tuple[str, FailureClass, str, bool], ...] = (
    ("insufficient_funds", FailureClass.INSUFFICIENT_FUNDS, "customer", False),

    ("transaction_limit_exceeded", FailureClass.LIMIT_EXCEEDED, "customer", False),
    ("transaction_daily_limit_exceeded", FailureClass.LIMIT_EXCEEDED, "customer", False),
    ("transaction_frequency_limit_exceeded", FailureClass.LIMIT_EXCEEDED, "customer", True),
    ("transaction_daily_count_exceeded", FailureClass.LIMIT_EXCEEDED, "gateway", True),
    ("credit_limit_exceeded", FailureClass.LIMIT_EXCEEDED, "gateway", False),
    ("mcc_amount_limit_exceeded", FailureClass.LIMIT_EXCEEDED, "gateway", True),

    ("payment_risk_check_failed", FailureClass.RISK_DECLINE, "gateway", False),
    ("payment_declined", FailureClass.RISK_DECLINE, "gateway", False),
    ("card_declined", FailureClass.RISK_DECLINE, "gateway", False),
    ("debit_declined", FailureClass.RISK_DECLINE, "gateway", True),
    ("authorisation_declined_by_psp", FailureClass.RISK_DECLINE, "gateway", True),
    ("credit_not_permitted", FailureClass.RISK_DECLINE, "gateway", True),

    ("bank_not_available", FailureClass.ISSUER_DOWN, "gateway", False),
    ("bank_technical_error", FailureClass.ISSUER_DOWN, "gateway", False),
    ("issuer_technical_error", FailureClass.ISSUER_DOWN, "gateway", False),
    ("bank_cutoff_in_progress", FailureClass.ISSUER_DOWN, "gateway", True),

    ("gateway_technical_error", FailureClass.PSP_TIMEOUT, "gateway", False),
    ("psp_not_available", FailureClass.PSP_TIMEOUT, "gateway", False),
    ("psp_app_not_available", FailureClass.PSP_TIMEOUT, "gateway", False),
    ("upi_app_technical_error", FailureClass.PSP_TIMEOUT, "gateway", True),
    ("payment_declined_due_to_high_traffic", FailureClass.PSP_TIMEOUT, "gateway", True),

    ("request_timed_out", FailureClass.NETWORK_TIMEOUT, "gateway", False),
    ("invalid_response_from_gateway", FailureClass.NETWORK_TIMEOUT, "gateway", False),
    ("vpa_resolution_failed", FailureClass.NETWORK_TIMEOUT, "gateway", True),

    ("authentication_failed", FailureClass.AUTH_ABANDONED, "customer", False),
    ("incorrect_otp", FailureClass.AUTH_ABANDONED, "customer", False),
    ("incorrect_pin", FailureClass.AUTH_ABANDONED, "customer", False),
    ("otp_attempts_exceeded", FailureClass.AUTH_ABANDONED, "customer", True),
    ("pin_attempts_exceeded", FailureClass.AUTH_ABANDONED, "customer", True),
    ("incorrect_cvv", FailureClass.AUTH_ABANDONED, "customer", False),

    ("payment_timed_out", FailureClass.AUTH_TIMEOUT, "customer", False),
    ("otp_expired", FailureClass.AUTH_TIMEOUT, "customer", False),
    ("payment_session_expired", FailureClass.AUTH_TIMEOUT, "gateway", False),
    ("payment_collect_request_expired", FailureClass.AUTH_TIMEOUT, "gateway", True),

    ("payment_cancelled", FailureClass.USER_CANCELLED, "customer", False),

    ("bank_account_invalid", FailureClass.ACCOUNT_CLOSED, "customer", False),
    ("beneficiary_account_does_not_exist", FailureClass.ACCOUNT_CLOSED, "gateway", False),
    ("beneficiary_account_dormant", FailureClass.ACCOUNT_CLOSED, "gateway", True),
    ("debit_instrument_inactive", FailureClass.ACCOUNT_CLOSED, "gateway", True),

    ("debit_instrument_blocked", FailureClass.CARD_BLOCKED, "customer", False),
    ("transaction_on_vpa_restricted", FailureClass.CARD_BLOCKED, "gateway", True),

    ("card_expired", FailureClass.INVALID_INSTRUMENT, "customer", False),
    ("card_number_invalid", FailureClass.INVALID_INSTRUMENT, "customer", False),
    ("invalid_vpa", FailureClass.INVALID_INSTRUMENT, "customer", False),
    ("incorrect_card_expiry_date", FailureClass.INVALID_INSTRUMENT, "customer", True),
    ("card_not_enrolled", FailureClass.INVALID_INSTRUMENT, "customer", True),

    ("mandate_creation_declined", FailureClass.MANDATE_REVOKED, "gateway", False),
    ("reqauth_mandate_not_acknowledged", FailureClass.MANDATE_REVOKED, "gateway", True),
)


def _merge_razorpay_reasons() -> None:
    """Fold the published reasons into the catalogue."""
    for reason, failure_class, _source, holdout in RAZORPAY_REASONS:
        existing = ERROR_CATALOGUE.get(failure_class, ())
        ERROR_CATALOGUE[failure_class] = existing + (
            ErrorTemplate(reason, holdout=holdout),)


_merge_razorpay_reasons()


def razorpay_source_alignment() -> dict:
    """How Razorpay's `source` field lines up with this project's disposition.

    Reported because the two vocabularies were designed independently: theirs
    to route an error to whoever can fix it, ours to decide what intervention
    could recover the payment. Where they agree, the grouping is probably not
    arbitrary.
    """
    table: dict[str, dict[str, int]] = {}
    for _reason, failure_class, source, _ in RAZORPAY_REASONS:
        row = table.setdefault(source, {})
        key = failure_class.disposition.name
        row[key] = row.get(key, 0) + 1
    return table


def templates_for(
    failure_class: FailureClass, rail: Rail, include_holdout: bool = True
) -> tuple[ErrorTemplate, ...]:
    """Templates valid for this class on this rail."""
    candidates = ERROR_CATALOGUE.get(failure_class, ())
    out = tuple(
        t for t in candidates
        if (t.rails is None or rail in t.rails)
        and (include_holdout or not t.holdout)
    )
    return out or candidates


def raw_error_for(
    failure_class: FailureClass | None, rail: Rail, seed: int, *keys: object
) -> str | None:
    """Pick a decline string deterministically for a simulated failure."""
    if failure_class is None:
        return None
    options = templates_for(failure_class, rail)
    if not options:
        return failure_class.name
    idx = int(uniform(seed, "errtext", failure_class.name, *keys) * len(options))
    return options[min(idx, len(options) - 1)].text


def all_strings(include_holdout: bool = True) -> list[tuple[str, FailureClass, bool]]:
    """Flat catalogue of (text, true class, is_holdout) for evaluation."""
    rows: list[tuple[str, FailureClass, bool]] = []
    for fc, templates in ERROR_CATALOGUE.items():
        for t in templates:
            if t.holdout and not include_holdout:
                continue
            rows.append((t.text, fc, t.holdout))
    return rows


def catalogue_stats() -> dict[str, int]:
    strings = all_strings()
    return {
        "classes": len(ERROR_CATALOGUE),
        "total_strings": len(strings),
        "holdout_strings": sum(1 for _, _, h in strings if h),
        "visible_strings": sum(1 for _, _, h in strings if not h),
    }
