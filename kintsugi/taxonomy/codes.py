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

Codes below are the real ISO 8583 and NPCI response codes; the wrapper text is
representative rather than copied from any particular provider.
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
        ErrorTemplate("U67: Per transaction limit exceeded", rails=UPI_RAILS),
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
