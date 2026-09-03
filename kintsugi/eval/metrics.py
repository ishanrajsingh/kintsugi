"""Outcome metrics for a single policy run.

Deliberately several numbers rather than one. A recovery agent can always buy
a higher recovery rate by contacting people more, so a single headline metric
is an invitation to game it -- which is exactly what the naive baseline does.
Reporting recovery, cost, contact intensity and induced churn side by side
makes that trade visible instead of hiding it inside an average.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from kintsugi import calibration as cal
from kintsugi.domain import FailureClass, Paise, Payment
from kintsugi.world.simulator import SimulationResult


@dataclass(frozen=True, slots=True)
class RunMetrics:
    policy: str

    # -- population --------------------------------------------------------
    payments: int
    failed_first_attempt: int
    failed_gmv_paise: Paise
    """Total value at risk: the GMV of payments whose first attempt failed.
    This is the denominator that matters -- payments that authorised straight
    away were never the agent's to win."""

    # -- outcome -----------------------------------------------------------
    recovered: int
    recovered_gmv_paise: Paise
    churned: int

    # -- effort ------------------------------------------------------------
    retries: int
    nudges: int
    retry_cost_paise: Paise
    nudge_cost_paise: Paise

    # -- derived -----------------------------------------------------------
    @property
    def recovery_rate(self) -> float:
        """Share of *recoverable* payments recovered."""
        return self.recovered / self.failed_first_attempt if self.failed_first_attempt else 0.0

    @property
    def gmv_recovery_rate(self) -> float:
        return (self.recovered_gmv_paise / self.failed_gmv_paise
                if self.failed_gmv_paise else 0.0)

    @property
    def total_cost_paise(self) -> Paise:
        return self.retry_cost_paise + self.nudge_cost_paise

    @property
    def net_value_paise(self) -> float:
        """Recovered value less the cost of recovering it. The headline."""
        return self.recovered_gmv_paise - self.total_cost_paise

    @property
    def cost_per_rupee_recovered(self) -> float:
        return (self.total_cost_paise / self.recovered_gmv_paise
                if self.recovered_gmv_paise else float("inf"))

    @property
    def retries_per_recovery(self) -> float:
        return self.retries / self.recovered if self.recovered else float("inf")

    @property
    def contacts_per_recovery(self) -> float:
        return self.nudges / self.recovered if self.recovered else float("inf")

    @property
    def wasted_retries(self) -> int:
        """Retries that could not possibly have succeeded.

        Counted only where the ground truth is unambiguous: attempts made after
        a terminal failure class was already observed. A dead card cannot be
        revived, so every one of these is pure cost -- gateway load, issuer
        trust, and a customer watching their payment fail again.
        """
        return self._wasted

    _wasted: int = 0

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_wasted", None)
        d.update({
            "recovery_rate": self.recovery_rate,
            "gmv_recovery_rate": self.gmv_recovery_rate,
            "net_value_paise": self.net_value_paise,
            "total_cost_paise": self.total_cost_paise,
            "cost_per_rupee_recovered": self.cost_per_rupee_recovered,
            "retries_per_recovery": self.retries_per_recovery,
            "contacts_per_recovery": self.contacts_per_recovery,
            "wasted_retries": self.wasted_retries,
        })
        return d


def compute(result: SimulationResult) -> RunMetrics:
    """Score one simulation run."""
    failed = [p for p in result.payments
              if p.attempts and not p.attempts[0].succeeded]

    recovered = [p for p in failed if p.is_recovered]
    retries = sum(p.retry_count for p in result.payments)
    nudges = sum(p.nudge_count for p in result.payments)

    churned = sum(
        1 for e in result.ledger if e.outcome == "churned")

    return RunMetrics(
        policy=result.policy_name,
        payments=len(result.payments),
        failed_first_attempt=len(failed),
        failed_gmv_paise=sum(p.amount_paise for p in failed),
        recovered=len(recovered),
        recovered_gmv_paise=sum(p.amount_paise for p in recovered),
        churned=churned,
        retries=retries,
        nudges=nudges,
        retry_cost_paise=retries * cal.RETRY_ATTEMPT_COST_PAISE.v,
        nudge_cost_paise=sum(p.nudge_cost_paise for p in result.payments),
        _wasted=_count_wasted(result.payments),
    )


def _count_wasted(payments: list[Payment]) -> int:
    wasted = 0
    for p in payments:
        seen_terminal = False
        for attempt in p.attempts:
            if seen_terminal:
                wasted += 1
            if (attempt.failure_class is not None
                    and attempt.failure_class.is_terminal):
                seen_terminal = True
    return wasted


def by_failure_class(result: SimulationResult) -> dict[str, dict]:
    """Recovery broken down by the cause of the original failure.

    The most diagnostic view in the project. It is where you see whether a
    policy is recovering payments because it is smart or merely because it is
    persistent -- and whether it is still hammering causes that can never
    recover.
    """
    buckets: dict[str, dict] = {}
    for p in result.payments:
        if not p.attempts or p.attempts[0].succeeded:
            continue
        cause = p.attempts[0].failure_class
        key = cause.name if cause else "UNKNOWN"
        b = buckets.setdefault(key, {
            "failed": 0, "recovered": 0, "retries": 0, "nudges": 0,
            "gmv_paise": 0, "recovered_gmv_paise": 0,
            "disposition": cause.disposition.name if cause else "UNKNOWN",
        })
        b["failed"] += 1
        b["retries"] += p.retry_count
        b["nudges"] += p.nudge_count
        b["gmv_paise"] += p.amount_paise
        if p.is_recovered:
            b["recovered"] += 1
            b["recovered_gmv_paise"] += p.amount_paise

    for b in buckets.values():
        b["recovery_rate"] = b["recovered"] / b["failed"] if b["failed"] else 0.0
        b["retries_per_recovery"] = (
            b["retries"] / b["recovered"] if b["recovered"] else float("inf"))
    return buckets
