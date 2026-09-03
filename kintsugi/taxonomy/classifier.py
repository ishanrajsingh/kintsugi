"""Resolve raw gateway decline strings to the canonical taxonomy.

The cascade, cheapest first:

1. **Rules** (:mod:`kintsugi.taxonomy.rules`) -- free, instant, deterministic,
   and sufficient for the few hundred strings that make up nearly all real
   traffic.
2. **Cache** -- a string seen once is never sent to a model again. Decline
   vocabularies are small and highly repetitive, so the cache converges fast
   and the steady-state model spend is approximately zero.
3. **Model** -- only for genuinely novel strings.
4. **UNKNOWN** -- if there is no model, or it returns something invalid.

Why the model sits here and nowhere else
----------------------------------------
This is open-ended natural language written by hundreds of institutions with no
shared vocabulary, which drifts without notice. That is the thing language
models are actually better at than a rule table. It is also a *safe* place to
put one: the output is constrained to thirteen known labels, it is validated
against the enum, it is cached and auditable, and a wrong answer degrades one
payment's handling rather than corrupting a decision loop. Contrast the money
decision, where a fluent wrong answer would be indistinguishable from a right
one and would price a retry incorrectly with no way to notice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from kintsugi.domain import FailureClass
from kintsugi.taxonomy import rules
from kintsugi.taxonomy.providers import LLMProvider, NullProvider, default_provider

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "taxonomy_cache.json"

_VALID = {fc.name for fc in FailureClass if fc is not FailureClass.UNKNOWN}

PROMPT = """You are classifying decline messages from Indian payment gateways \
(UPI/NPCI, card networks, netbanking). Map the message to exactly one canonical \
cause.

Labels and what they mean:
- INSUFFICIENT_FUNDS: the payer's balance did not cover the amount
- LIMIT_EXCEEDED: a per-transaction, daily, or velocity limit was hit
- RISK_DECLINE: the issuer refused on risk/policy grounds (incl. do-not-honour, \
restricted card, no reason given)
- ISSUER_DOWN: the payer's bank or its switch was unavailable or timed out
- PSP_TIMEOUT: the payment gateway/acquirer did not respond in time
- NETWORK_TIMEOUT: transport-level failure between systems
- AUTH_ABANDONED: the customer never completed authentication (no PIN/OTP entered)
- AUTH_TIMEOUT: the authentication or collect request expired before the customer acted
- USER_CANCELLED: the customer actively cancelled or declined
- ACCOUNT_CLOSED: the account is closed, dormant, frozen, or no longer operative
- CARD_BLOCKED: the instrument is blocked, hotlisted, lost, or stolen
- INVALID_INSTRUMENT: the instrument details are wrong, expired, or deregistered
- MANDATE_REVOKED: a standing instruction or autopay mandate was cancelled

Distinguish carefully:
- AUTH_ABANDONED (customer never acted) vs AUTH_TIMEOUT (the window expired) vs \
USER_CANCELLED (customer actively refused)
- ACCOUNT_CLOSED (the account is gone) vs CARD_BLOCKED (the instrument is barred) \
vs INVALID_INSTRUMENT (the details are wrong)
- ISSUER_DOWN (the payer's bank) vs PSP_TIMEOUT (the gateway/acquirer side)

Message: "{message}"

Reply with the label only, nothing else."""


@dataclass(frozen=True, slots=True)
class Resolution:
    failure_class: FailureClass
    source: str
    """One of: rule, cache, llm, unknown."""
    detail: str | None = None

    @property
    def is_known(self) -> bool:
        return self.failure_class is not FailureClass.UNKNOWN


class TaxonomyResolver:
    """Rules, then cache, then a model, then give up honestly."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        cache_path: Path = CACHE_PATH,
        use_llm: bool = True,
    ) -> None:
        self.cache_path = cache_path
        self.cache: dict[str, str] = self._load_cache()
        self._provider = provider
        self.use_llm = use_llm
        self.stats = {"rule": 0, "cache": 0, "llm": 0, "unknown": 0,
                      "llm_invalid": 0}

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = default_provider() if self.use_llm else NullProvider()
        return self._provider

    # -- cache -----------------------------------------------------------

    def _load_cache(self) -> dict[str, str]:
        if self.cache_path.exists():
            try:
                return json.loads(self.cache_path.read_text())
            except json.JSONDecodeError:
                return {}
        return {}

    def save_cache(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(
            dict(sorted(self.cache.items())), indent=2))

    # -- resolution ------------------------------------------------------

    def classify(self, raw: str | None) -> Resolution:
        if not raw:
            self.stats["unknown"] += 1
            return Resolution(FailureClass.UNKNOWN, "unknown")

        predicted, pattern = rules.classify(raw)
        if predicted is not FailureClass.UNKNOWN:
            self.stats["rule"] += 1
            return Resolution(predicted, "rule", pattern)

        key = raw.strip().lower()
        if key in self.cache:
            self.stats["cache"] += 1
            return Resolution(FailureClass[self.cache[key]], "cache")

        if not self.use_llm:
            self.stats["unknown"] += 1
            return Resolution(FailureClass.UNKNOWN, "unknown")

        label = self._ask_model(raw)
        if label is None:
            self.stats["unknown"] += 1
            return Resolution(FailureClass.UNKNOWN, "unknown")

        self.cache[key] = label
        self.stats["llm"] += 1
        return Resolution(FailureClass[label], "llm", self.provider.name)

    def _ask_model(self, raw: str) -> str | None:
        provider = self.provider
        if isinstance(provider, NullProvider):
            return None
        text = provider.complete(PROMPT.format(message=raw), max_tokens=24)
        label = _parse_label(text)
        if label is None:
            self.stats["llm_invalid"] += 1
        return label

    def classify_many(self, strings, verbose: bool = False) -> dict[str, Resolution]:
        out: dict[str, Resolution] = {}
        for i, raw in enumerate(strings, 1):
            out[raw] = self.classify(raw)
            if verbose and i % 5 == 0:
                print(f"    {i}/{len(strings)} strings resolved")
        self.save_cache()
        return out


def _parse_label(text: str | None) -> str | None:
    """Pull a valid label out of the model's reply, or return None.

    Deliberately strict. A constrained-vocabulary task with an unconstrained
    decoder needs validation at the boundary: anything not in the enum is
    treated as a refusal rather than coerced into the nearest guess, because a
    silently wrong class propagates into retry decisions.
    """
    if not text:
        return None
    upper = text.upper()
    # Prefer an exact standalone token; fall back to any label mentioned.
    for token in re.findall(r"[A-Z_]{4,}", upper):
        if token in _VALID:
            return token
    for label in _VALID:
        if label in upper:
            return label
    return None
