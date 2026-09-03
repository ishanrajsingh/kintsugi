"""Deterministic rules mapping gateway decline strings onto the taxonomy.

These rules were authored by reading **only** the non-holdout templates in
:mod:`kintsugi.taxonomy.codes`, which now include Razorpay's own published
``reason`` identifiers alongside the wire-level ISO 8583 and NPCI codes. The held-out strings were never looked at while
writing them, which is what makes the held-out accuracy number meaningful
rather than circular.

This is the layer that should handle the overwhelming majority of production
traffic, because the overwhelming majority of production traffic is the same
few hundred strings over and over. Rules are free, instant, deterministic and
auditable, and a system that sends every routine ``"51 - Insufficient funds"``
to a language model is burning money and latency to relearn what it already
knows. The model's job is the tail -- and the tail is real, because banks ship
new decline templates without telling anyone.

Order matters. The patterns are tried in sequence and the first match wins, so
more specific patterns precede more general ones: "OTP expired" is an
authentication timeout, not an expired card, even though both say "expired".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from kintsugi.domain import FailureClass


@dataclass(frozen=True, slots=True)
class Rule:
    pattern: re.Pattern
    failure_class: FailureClass
    note: str = ""


def _rule(regex: str, fc: FailureClass, note: str = "") -> Rule:
    return Rule(re.compile(regex, re.IGNORECASE), fc, note)


#: Tried in order; first match wins.
#:
#: These cover the wire-level codes *and* Razorpay's published ``reason``
#: identifiers, which are snake_case rather than prose -- so most patterns admit
#: either an underscore or a space between words.
#:
#: Identifier patterns are anchored with a trailing ``\b``. Underscore is a word
#: character, so this makes them match a *whole* identifier and not a prefix of
#: a longer one -- ``payment_declined`` no longer swallows
#: ``payment_declined_due_to_high_traffic``, which is a different cause
#: entirely. This is a general rule about matching identifiers rather than
#: prose, applied without reference to the held-out set: over-matching a prefix
#: is the failure mode that turns a safe `UNKNOWN` into a confident wrong
#: answer, which is strictly worse.
RULES: tuple[Rule, ...] = (
    # --- authentication timing, before anything matching "expired" ------
    _rule(r"\bU69\b|collect request expired|session expired|otp expired"
          r"|otp[_ ]expired|payment[_ ]timed[_ ]out\b|payment[_ ]session[_ ]expired\b"
          r"|timeout[_ ]at[_ ]acs",
          FailureClass.AUTH_TIMEOUT,
          "must precede the expired-card rule"),

    # --- explicit cancellation, before generic abandonment --------------
    _rule(r"cancelled by user|user[_ ]aborted|payment[_ ]cancelled\b"
          r"|declined the collect request",
          FailureClass.USER_CANCELLED),

    # --- authentication abandonment -------------------------------------
    _rule(r"\bZM\b|invalid or missing mpin|did not complete authentication"
          r"|3ds[_ ]authentication[_ ]abandoned|otp not entered"
          r"|dropped off at bank page|collect request not approved"
          r"|authentication[_ ]failed\b|incorrect[_ ](otp|pin|cvv)\b"
          r"|(otp|pin)[_ ]attempts[_ ]exceeded\b",
          FailureClass.AUTH_ABANDONED),

    # --- terminal instrument --------------------------------------------
    _rule(r"^41\b|^43\b|lost card|stolen card|card has been blocked"
          r"|\bcard[_ ]blocked\b|debit[_ ]instrument[_ ]blocked\b",
          FailureClass.CARD_BLOCKED),
    _rule(r"^54\b|expired card|card[_ ]expired|invalid card number"
          r"|card[_ ]number[_ ]invalid\b|vpa does not exist|invalid[_ ]vpa\b"
          r"|invalid[_ ]instrument[_ ]details",
          FailureClass.INVALID_INSTRUMENT),
    _rule(r"^14\b|account closed|dormant|account[_ ]inactive"
          r"|bank[_ ]account[_ ]invalid\b|beneficiary account frozen"
          r"|beneficiary[_ ]account[_ ]does[_ ]not[_ ]exist",
          FailureClass.ACCOUNT_CLOSED),
    _rule(r"mandate has been revoked|umn not found|umn.*cancelled"
          r"|subscription[_ ]cancelled|mandate[_ ]creation[_ ]declined\b",
          FailureClass.MANDATE_REVOKED),

    # --- balance ---------------------------------------------------------
    _rule(r"^51\b|\bZ9\b|insufficient[_ ](funds|balance)|\bNSF\b"
          r"|does not have sufficient balance|low balance",
          FailureClass.INSUFFICIENT_FUNDS),

    # --- limits ----------------------------------------------------------
    _rule(r"^61\b|^65\b|\bZ7\b|\bZ8\b|exceeds withdrawal"
          r"|per transaction limit|daily limit|txn[_ ]limit[_ ]breached"
          r"|limit.*reached|transaction[_ ](daily[_ ])?(limit|count)[_ ]exceeded"
          r"|transaction[_ ]frequency[_ ]limit[_ ]exceeded"
          r"|credit[_ ]limit[_ ]exceeded\b|too many transactions",
          FailureClass.LIMIT_EXCEEDED),

    # --- issuer infrastructure, before the generic timeout rules --------
    _rule(r"^91\b|^96\b|\bU30\b|\bBT\b|bank timed out|bank server"
          r"|issuer[_ ]unavailable|system malfunction|bank[_ ]not[_ ]available"
          r"|bank[_ ]technical[_ ]error\b|issuer[_ ]technical[_ ]error\b",
          FailureClass.ISSUER_DOWN),

    # --- gateway / network ----------------------------------------------
    _rule(r"gateway[_ ]error|504|gateway timeout|psp did not respond"
          r"|payment[_ ]gateway[_ ]timeout|gateway[_ ]technical[_ ]error"
          r"|psp(_app)?[_ ]not[_ ]available\b",
          FailureClass.PSP_TIMEOUT),
    _rule(r"network error|connection[_ ]reset|socket timeout|npci unreachable"
          r"|request[_ ]timed[_ ]out\b|invalid[_ ]response[_ ]from[_ ]gateway\b",
          FailureClass.NETWORK_TIMEOUT),

    # --- issuer risk, last because its language is the vaguest ----------
    _rule(r"^05\b|^57\b|\bU16\b|do not honor|do not honour"
          r"|declined by issuing bank|declined[_ ]by[_ ]risk[_ ]engine"
          r"|risk threshold|blocked for security|not permitted to cardholder"
          r"|payment[_ ]risk[_ ]check[_ ]failed\b|payment[_ ]declined\b"
          r"|card[_ ]declined\b",
          FailureClass.RISK_DECLINE),
)


def classify(raw: str | None) -> tuple[FailureClass, str | None]:
    """Map a raw decline string to a class, or ``UNKNOWN`` if no rule matches.

    Returns the class and the pattern that matched, so a decision can be
    audited back to the specific rule responsible.
    """
    if not raw:
        return FailureClass.UNKNOWN, None
    for rule in RULES:
        if rule.pattern.search(raw):
            return rule.failure_class, rule.pattern.pattern
    return FailureClass.UNKNOWN, None


def coverage() -> dict:
    """Rule accuracy on the visible catalogue versus the held-out strings.

    The gap between the two is the whole argument for having a model at all.
    """
    from kintsugi.taxonomy.codes import all_strings

    stats = {
        "visible": {"n": 0, "correct": 0, "unmatched": 0},
        "holdout": {"n": 0, "correct": 0, "unmatched": 0},
    }
    misses: list[dict] = []

    for text, truth, is_holdout in all_strings():
        bucket = stats["holdout" if is_holdout else "visible"]
        predicted, _ = classify(text)
        bucket["n"] += 1
        if predicted is truth:
            bucket["correct"] += 1
        else:
            if predicted is FailureClass.UNKNOWN:
                bucket["unmatched"] += 1
            misses.append({
                "text": text,
                "truth": truth.name,
                "predicted": predicted.name,
                "holdout": is_holdout,
            })

    for bucket in stats.values():
        bucket["accuracy"] = (
            bucket["correct"] / bucket["n"] if bucket["n"] else 0.0)
    stats["misses"] = misses
    return stats
