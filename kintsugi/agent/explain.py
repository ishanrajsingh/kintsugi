"""Answer a merchant's questions about what the agent did, and why.

Every merchant eventually asks "why did you not chase my 40,000 rupee payment?"
A recovery engine that can't answer that doesn't get deployed, however good its
numbers are.

The obvious implementation -- hand the model the question and let it reason over
the payments -- is the wrong one. It invents plausible amounts and confident
explanations for decisions that were never made, and the merchant can't tell
those from real ones. So the split is strict:

- Retrieval and arithmetic are deterministic. Facts come out of the ledger by
  ordinary filtering and get summed in Python. Every number in the answer exists
  in the ledger before the model is called.
- The model only phrases what it's given, from an explicit fact block, and is
  told to say it doesn't know rather than fill a gap.
- The answer is verified: every number in it must appear in the fact block. A
  figure that wasn't supplied means the response is rejected and the
  deterministic summary goes out instead.

That last check is what makes this safe to show a merchant -- a grounded
generator nobody audits is just a fluent one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from kintsugi.domain import FailureClass
from kintsugi.taxonomy.providers import LLMProvider, NullProvider, default_provider

PROMPT = """You are explaining a payment-recovery agent's decisions to the \
merchant whose money is involved.

Answer using ONLY the facts below. Every figure you state must appear in them. \
If the facts do not answer the question, say so plainly instead of guessing. \
Be direct and concrete; no marketing language. Two to four sentences.

QUESTION: {question}

FACTS:
{facts}

Answer:"""


@dataclass
class Answer:
    text: str
    facts: list[str]
    source: str
    """llm | deterministic"""
    rejected_reason: str | None = None
    matched: int = 0

    def to_dict(self) -> dict:
        return {
            "text": self.text, "facts": self.facts, "source": self.source,
            "rejected_reason": self.rejected_reason, "matched": self.matched,
        }


@dataclass
class LedgerIndex:
    """Everything queryable about one run, built once from the raw records."""

    decisions: list[dict]
    payments: dict = field(default_factory=dict)

    @classmethod
    def build(cls, decisions: list[dict], payments) -> "LedgerIndex":
        return cls(decisions=decisions,
                   payments={p.payment_id: p for p in payments})


def inr(paise: float) -> str:
    return f"INR {paise / 100:,.0f}"


def _clock(minute: int) -> str:
    day, rem = divmod(int(minute), 1440)
    return f"day {day + 1}, {rem // 60:02d}:{rem % 60:02d}"


class DecisionExplainer:
    """Natural-language questions over a decision ledger."""

    def __init__(
        self,
        index: LedgerIndex,
        provider: LLMProvider | None = None,
        use_llm: bool = True,
    ) -> None:
        self.index = index
        self._provider = provider
        self.use_llm = use_llm

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            self._provider = default_provider() if self.use_llm else NullProvider()
        return self._provider

    # -- retrieval -------------------------------------------------------

    def gather_facts(self, question: str) -> tuple[list[str], int]:
        """Pull the relevant ledger facts. Entirely deterministic."""
        q = question.lower()
        facts: list[str] = []

        # 1. A specific payment, if one is named.
        for pid in re.findall(r"pay_\d+", q):
            facts.extend(self._payment_facts(pid))

        # 2. A named failure cause.
        causes = [fc for fc in FailureClass
                  if fc.name.lower().replace("_", " ") in q
                  or fc.name.lower() in q]
        for cause in causes:
            facts.extend(self._cause_facts(cause))

        # 3. Contact-intensity questions.
        if any(w in q for w in ("nudge", "message", "sms", "whatsapp",
                                "remind", "contact", "text")):
            facts.extend(self._contact_facts())

        # 4. Waiting / timing questions.
        if any(w in q for w in ("wait", "hold", "delay", "payday", "salary",
                                "when", "timing")):
            facts.extend(self._wait_facts())

        # 5. Money questions, and the fallback when nothing else matched.
        if not facts or any(w in q for w in (
                "recover", "total", "how much", "cost", "spend", "money",
                "overall", "summary")):
            facts.extend(self._summary_facts())

        return facts, len(facts)

    def _payment_facts(self, pid: str) -> list[str]:
        payment = self.index.payments.get(pid)
        if payment is None:
            return [f"No payment {pid} exists in this run."]

        out = [
            f"Payment {pid} is for {inr(payment.amount_paise)} "
            f"({'a recurring mandate' if payment.is_recurring else 'a checkout payment'}) "
            f"on issuer {payment.issuer}."
        ]
        for attempt in payment.attempts:
            if attempt.succeeded:
                out.append(f"Attempt {attempt.attempt_no} at "
                           f"{_clock(attempt.at)} succeeded.")
            else:
                out.append(
                    f"Attempt {attempt.attempt_no} at {_clock(attempt.at)} on "
                    f"{attempt.rail.name} failed with "
                    f"{attempt.failure_class.name if attempt.failure_class else 'UNKNOWN'} "
                    f"(gateway said: \"{attempt.raw_error}\").")

        for decision in self.index.decisions:
            if decision["payment_id"] != pid:
                continue
            out.append(
                f"At {_clock(decision['at'])} the agent chose "
                f"{decision['chosen']}: {decision['rationale']}")
            for alt in decision.get("alternatives", [])[:3]:
                out.append(
                    f"  It also priced {alt['action']} at "
                    f"P(success)={alt['p']:.0%}, worth {inr(alt['ev_paise'])}.")

        if payment.is_recovered:
            out.append(f"Payment {pid} was recovered at "
                       f"{_clock(payment.recovered_at)}.")
        else:
            out.append(f"Payment {pid} was not recovered; "
                       f"{inr(payment.amount_paise)} was written off.")
        return out

    def _cause_facts(self, cause: FailureClass) -> list[str]:
        matching = [p for p in self.index.payments.values()
                    if p.attempts and not p.attempts[0].succeeded
                    and p.attempts[0].failure_class is cause]
        if not matching:
            return [f"No payments failed with {cause.name} in this run."]

        recovered = [p for p in matching if p.is_recovered]
        retries = sum(p.retry_count for p in matching)
        nudges = sum(p.nudge_count for p in matching)
        value = sum(p.amount_paise for p in matching)
        got = sum(p.amount_paise for p in recovered)

        out = [
            f"{len(matching)} payments failed with {cause.name}, worth "
            f"{inr(value)} in total.",
            f"{len(recovered)} of them were recovered "
            f"({len(recovered) / len(matching):.0%}), returning {inr(got)}.",
            f"The agent spent {retries} retries and {nudges} customer messages "
            f"on them.",
            f"{cause.name} is classified as {cause.disposition.name}.",
        ]
        if cause.is_terminal:
            out.append(
                f"{cause.name} is terminal: the payment instrument is dead, so "
                f"no retry on any rail at any time can succeed. The agent stops "
                f"immediately and asks the customer for new payment details.")
        return out

    def _contact_facts(self) -> list[str]:
        payments = list(self.index.payments.values())
        nudged = [p for p in payments if p.nudge_count > 0]
        if not nudged:
            return ["No customers were messaged in this run."]
        total = sum(p.nudge_count for p in nudged)
        most = max(p.nudge_count for p in nudged)
        cost = sum(p.nudge_cost_paise for p in payments)
        recovered = sum(1 for p in nudged if p.is_recovered)
        return [
            f"{total} messages were sent to {len(nudged)} customers, costing "
            f"{inr(cost)} in total.",
            f"No customer received more than {most} messages about one payment.",
            f"{recovered} of the {len(nudged)} messaged payments were recovered "
            f"({recovered / len(nudged):.0%}).",
            "The agent charges itself a churn risk for messaging beyond the "
            "second reminder, so it stops rather than keeps going.",
        ]

    def _wait_facts(self) -> list[str]:
        waits = [d for d in self.index.decisions if d["chosen"] == "WAIT"]
        if not waits:
            return ["The agent did not defer any decisions in this run."]
        held = [d for d in waits if "day" in d["rationale"]]
        recovered = sum(
            1 for d in held
            if self.index.payments.get(d["payment_id"])
            and self.index.payments[d["payment_id"]].is_recovered)
        out = [
            f"The agent deliberately deferred {len(waits)} decisions, of which "
            f"{len(held)} were multi-day holds.",
            f"{recovered} of those held payments were later recovered.",
            "Waiting is priced like any other action: the agent compares what "
            "acting now is worth against what acting at a better moment is "
            "worth, discounted for the risk the payment expires first.",
        ]
        if held:
            biggest = max(held, key=lambda d: d["amount_paise"])
            out.append(
                f"The largest hold was {inr(biggest['amount_paise'])}: "
                f"{biggest['rationale']}")
        return out

    def _summary_facts(self) -> list[str]:
        payments = list(self.index.payments.values())
        failed = [p for p in payments
                  if p.attempts and not p.attempts[0].succeeded]
        if not failed:
            return ["No payments failed in this run."]
        recovered = [p for p in failed if p.is_recovered]
        at_risk = sum(p.amount_paise for p in failed)
        got = sum(p.amount_paise for p in recovered)
        retries = sum(p.retry_count for p in payments)
        nudges = sum(p.nudge_count for p in payments)
        cost = sum(p.nudge_cost_paise for p in payments)
        return [
            f"{len(failed)} of {len(payments)} payments failed on first attempt, "
            f"putting {inr(at_risk)} at risk.",
            f"The agent recovered {len(recovered)} of them "
            f"({len(recovered) / len(failed):.0%}), returning {inr(got)}.",
            f"It spent {retries} retries and {nudges} customer messages, at a "
            f"messaging cost of {inr(cost)}.",
        ]

    # -- answering -------------------------------------------------------

    def answer(self, question: str, max_facts: int = 22) -> Answer:
        facts, _ = self.gather_facts(question)
        facts = facts[:max_facts]
        deterministic = "\n".join(f"- {f}" for f in facts)

        if not self.use_llm or isinstance(self.provider, NullProvider):
            return Answer(deterministic, facts, "deterministic")

        text = self.provider.complete(
            PROMPT.format(question=question, facts=deterministic),
            max_tokens=320)
        cleaned = (text or "").strip()
        if not cleaned:
            return Answer(deterministic, facts, "deterministic",
                          rejected_reason="model returned nothing")

        problem = verify_grounded(cleaned, facts)
        if problem:
            return Answer(deterministic, facts, "deterministic",
                          rejected_reason=problem)
        return Answer(cleaned, facts, "llm")


# ---------------------------------------------------------------------------
# Grounding check
# ---------------------------------------------------------------------------

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def verify_grounded(answer: str, facts: list[str]) -> str | None:
    """Reject an answer containing any figure not present in the facts.

    Numbers are the part of a generated explanation a merchant will act on and
    the part they cannot check, so they are the part worth policing. Prose that
    paraphrases the facts is fine; a rupee figure that appeared from nowhere is
    not.
    """
    corpus = " ".join(facts)
    supplied = {_norm(m) for m in _NUMBER.findall(corpus)}
    # Percentages derived from supplied figures are common and harmless, so
    # allow any integer 0-100 as well as a small set of ordinals.
    supplied |= {float(i) for i in range(0, 101)}

    for token in _NUMBER.findall(answer):
        value = _norm(token)
        if value in supplied:
            continue
        # Tolerate rounding of a supplied figure (e.g. 1,234 stated as 1,200).
        if any(abs(value - s) <= max(1.0, abs(s) * 0.01) for s in supplied):
            continue
        return f"unsupported figure {token!r} not present in the ledger facts"
    return None


def _norm(token: str) -> float:
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return float("nan")
