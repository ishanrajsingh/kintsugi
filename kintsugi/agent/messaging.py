"""Customer-facing recovery copy, generated per failure cause.

Most dunning sends one message: *"Your payment failed, please try again."* For
most failures that message is useless, and for some it is actively harmful. A
customer whose balance was short does not need to be told to try again -- they
need to know how much and by when. A customer who closed the app before
entering their UPI PIN never saw a failure at all and needs a link back to a
half-finished action. A customer whose card was blocked by their bank cannot
solve anything without calling that bank, and telling them to retry sends them
into a loop that ends with them giving up on the merchant.

So the copy is generated per cause, and this is the second place a language
model genuinely earns its keep -- writing natural, situation-appropriate,
short-form copy in the customer's language is what it is for.

Guardrails, because this text goes to real people
-------------------------------------------------
Generated copy is *validated before use*, never trusted on faith:

* hard length limits per channel (an SMS that fragments costs twice and reads
  badly);
* no unresolved template placeholders;
* no invented specifics -- offers, deadlines, refunds, penalties or support
  phone numbers the system cannot honour;
* a deterministic template for every cause as the fallback.

If validation fails, the template ships. The customer never sees the model's
output unless it passed every check, and the system works with no model at all.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from kintsugi.domain import Channel, Disposition, FailureClass
from kintsugi.taxonomy.providers import LLMProvider, NullProvider, default_provider

CACHE_PATH = Path(__file__).resolve().parents[2] / "data" / "message_cache.json"

#: Channel limits. SMS is the binding one: 160 GSM-7 characters is a single
#: segment, and going one character over doubles the cost of every send.
MAX_LENGTH: dict[Channel, int] = {
    Channel.SMS: 160,
    Channel.WHATSAPP: 320,
    Channel.EMAIL: 500,
}

#: Words that would promise something the system cannot deliver. A model asked
#: to be helpful will reach for these; they must never reach a customer.
FORBIDDEN = re.compile(
    r"\b(refund|guarantee|guaranteed|free|discount|cashback|coupon|offer|"
    r"waive[dr]?|penalt(y|ies)|legal action|lawyer|court|credit score|"
    r"blacklist|call us at|helpline|1800[\s-]?\d+)\b",
    re.IGNORECASE,
)

PLACEHOLDER = re.compile(r"[{<]\s*[a-z_]+\s*[}>]", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Message:
    text: str
    source: str
    """template | llm"""
    cause: FailureClass
    channel: Channel


# ---------------------------------------------------------------------------
# Deterministic fallbacks: one per cause, always available, always safe.
# ---------------------------------------------------------------------------

TEMPLATES: dict[FailureClass, str] = {
    FailureClass.INSUFFICIENT_FUNDS:
        "Your payment of {amount} to {merchant} could not be completed because "
        "the account balance was short. Add funds and we will try again.",
    FailureClass.LIMIT_EXCEEDED:
        "Your payment of {amount} to {merchant} exceeded your bank's "
        "transaction limit. Try again tomorrow or use another method.",
    FailureClass.RISK_DECLINE:
        "Your bank declined the payment of {amount} to {merchant}. Approving it "
        "in your banking app, or using another method, usually resolves this.",
    FailureClass.AUTH_ABANDONED:
        "Your payment of {amount} to {merchant} is waiting for approval. "
        "Complete it here: {link}",
    FailureClass.AUTH_TIMEOUT:
        "The approval window for your {amount} payment to {merchant} expired. "
        "Start again here: {link}",
    FailureClass.USER_CANCELLED:
        "Your payment of {amount} to {merchant} was cancelled. If that was not "
        "intended, you can complete it here: {link}",
    FailureClass.ISSUER_DOWN:
        "Your bank was temporarily unavailable, so your {amount} payment to "
        "{merchant} did not go through. We will retry shortly.",
    FailureClass.PSP_TIMEOUT:
        "A temporary technical issue stopped your {amount} payment to "
        "{merchant}. We will retry shortly; no action is needed.",
    FailureClass.NETWORK_TIMEOUT:
        "A temporary connection issue stopped your {amount} payment to "
        "{merchant}. We will retry shortly; no action is needed.",
    FailureClass.CARD_BLOCKED:
        "Your card was declined by your bank for your {amount} payment to "
        "{merchant}. Please use a different payment method: {link}",
    FailureClass.ACCOUNT_CLOSED:
        "The account used for your {amount} payment to {merchant} is no longer "
        "active. Please add a different payment method: {link}",
    FailureClass.INVALID_INSTRUMENT:
        "The payment details for your {amount} payment to {merchant} are no "
        "longer valid. Please update them here: {link}",
    FailureClass.MANDATE_REVOKED:
        "The autopay instruction for {merchant} is no longer active, so the "
        "{amount} payment could not be collected. Set it up again: {link}",
    FailureClass.UNKNOWN:
        "Your payment of {amount} to {merchant} did not go through. "
        "You can complete it here: {link}",
}

_GUIDANCE: dict[Disposition, str] = {
    Disposition.TIME_HEALS:
        "The customer must add money or wait for a limit to reset. Do not tell "
        "them to simply retry now -- it will fail again.",
    Disposition.NEEDS_CUSTOMER:
        "The customer abandoned an authentication step and may not know the "
        "payment failed. Be warm, not accusatory, and give them the link.",
    Disposition.RAIL_SWITCH:
        "This was a bank or network problem, not the customer's fault. Say so "
        "plainly and tell them we are handling the retry.",
    Disposition.TERMINAL:
        "The payment instrument is dead. Do not suggest retrying it; ask for "
        "new payment details.",
    Disposition.UNKNOWN:
        "The cause is unclear. Stay generic and give them a way to complete it.",
}

PROMPT = """Write one {channel} message to an Indian customer whose payment failed.

Failure cause: {cause}
Situation: {guidance}
Amount: {amount}
Merchant: {merchant}

Rules:
- Under {limit} characters, plain text, no emoji, no subject line.
- Say what happened and the single next step. Nothing else.
- Do not invent offers, refunds, discounts, deadlines, penalties, or phone numbers.
- Do not promise anything beyond retrying the payment.
- Indian English, plain and respectful. No marketing tone.
{link_rule}

Reply with the message text only."""


class MessageWriter:
    """Cause-aware recovery copy with validation and a template fallback."""

    def __init__(
        self,
        provider: LLMProvider | None = None,
        cache_path: Path = CACHE_PATH,
        use_llm: bool = True,
    ) -> None:
        self.cache_path = cache_path
        self.cache: dict[str, str] = self._load()
        self._provider = provider
        self.use_llm = use_llm
        self.stats = {"template": 0, "cache": 0, "llm": 0, "rejected": 0}
        self.rejections: list[dict] = []

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = default_provider() if self.use_llm else NullProvider()
        return self._provider

    def _load(self) -> dict[str, str]:
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

    # -- generation ------------------------------------------------------

    def write(
        self,
        cause: FailureClass,
        channel: Channel,
        amount_paise: int,
        merchant: str = "the merchant",
        link: str = "pay.example.in/r/xxxx",
    ) -> Message:
        amount = _format_inr(amount_paise)
        fields = {"amount": amount, "merchant": merchant, "link": link}

        # Only a handful of (cause, channel) pairs exist, so the cache saturates
        # almost immediately and steady-state model cost is effectively zero.
        key = f"{cause.name}|{channel.name}"
        if key in self.cache:
            self.stats["cache"] += 1
            return Message(
                _fill(self.cache[key], fields), "cache", cause, channel)

        if self.use_llm:
            generated = self._generate(cause, channel, amount, merchant)
            if generated is not None:
                self.cache[key] = generated
                self.stats["llm"] += 1
                return Message(_fill(generated, fields), "llm", cause, channel)

        self.stats["template"] += 1
        return Message(
            _fill(TEMPLATES[cause], fields), "template", cause, channel)

    def _generate(
        self, cause: FailureClass, channel: Channel, amount: str, merchant: str
    ) -> str | None:
        provider = self.provider
        if isinstance(provider, NullProvider):
            return None

        limit = MAX_LENGTH[channel]
        needs_link = cause.disposition in (
            Disposition.NEEDS_CUSTOMER, Disposition.TERMINAL)
        link_rule = ("- End with the literal token {link} where a payment link "
                     "should go." if needs_link else
                     "- Do not include any link or URL.")

        text = provider.complete(
            PROMPT.format(
                channel=channel.name.lower(), cause=cause.name,
                guidance=_GUIDANCE[cause.disposition], amount=amount,
                merchant=merchant, limit=limit, link_rule=link_rule),
            max_tokens=180,
        )
        cleaned = _clean(text)
        problem = validate(cleaned, channel, needs_link)
        if problem:
            self.stats["rejected"] += 1
            self.rejections.append({
                "cause": cause.name, "channel": channel.name,
                "reason": problem, "text": (cleaned or "")[:200]})
            return None
        return cleaned

    def prewarm(self, verbose: bool = False) -> dict:
        """Generate and cache copy for every cause and channel up front.

        Recovery messaging must not wait on an inference call, so the whole
        matrix is generated ahead of time. It is small: thirteen causes by three
        channels, generated once and cached permanently.
        """
        for cause in FailureClass:
            for channel in Channel:
                self.write(cause, channel, 125_000)
                # Save after every entry, not at the end. Generating the full
                # matrix against a local model takes tens of minutes, and an
                # all-or-nothing write means an interrupted run throws away
                # every message it had already produced.
                self.save_cache()
                if verbose:
                    print(f"    {cause.name:20s} {channel.name}", flush=True)
        return dict(self.stats)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(text: str | None, channel: Channel, needs_link: bool) -> str | None:
    """Return a rejection reason, or ``None`` if the copy is safe to send."""
    if not text:
        return "empty"
    if len(text) > MAX_LENGTH[channel]:
        return f"too long ({len(text)} > {MAX_LENGTH[channel]})"
    if len(text) < 25:
        return "too short to be useful"
    match = FORBIDDEN.search(text)
    if match:
        return f"forbidden claim: {match.group(0)!r}"
    leftovers = [m for m in PLACEHOLDER.findall(text)
                 if m.strip("{}<> ").lower() not in {"amount", "merchant", "link"}]
    if leftovers:
        return f"unresolved placeholder: {leftovers[0]!r}"
    if needs_link and "{link}" not in text:
        return "missing required link token"
    if not needs_link and re.search(r"https?://|\bwww\.", text):
        return "unexpected URL"
    return None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    out = text.strip()
    # Models like to wrap copy in quotes or prefix it with a label.
    out = re.sub(r'^(message|sms|text|output)\s*[:\-]\s*', '', out,
                 flags=re.IGNORECASE)
    out = out.strip().strip('"').strip("'").strip()
    return " ".join(out.split())


def _fill(template: str, fields: dict) -> str:
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out


def _format_inr(paise: int) -> str:
    rupees = paise / 100
    if rupees >= 1000:
        # Indian digit grouping: 1,23,456 rather than 123,456.
        whole = f"{int(rupees):,}"
        parts = whole.replace(",", "")
        if len(parts) > 3:
            head, tail = parts[:-3], parts[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            whole = ",".join(groups + [tail])
        return f"INR {whole}"
    return f"INR {rupees:,.0f}"
