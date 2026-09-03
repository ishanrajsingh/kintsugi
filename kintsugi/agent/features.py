"""Feature extraction for the recovery predictors.

Every feature here is computable from the observable payment record plus the
health monitor's *inferred* issuer state. Nothing reads the simulator's latent
variables. That constraint is what makes the learned policy a candidate for a
real stack rather than an artefact of having the answer key.

The one that deserves comment is ``day_of_month``. The salary cycle is the
strongest timing signal available, but a merchant does not know any individual
customer's payday. What it *does* know is the calendar, and Indian salary
credit clusters hard at month start. So the model gets the calendar and has to
learn the population-level effect from outcomes -- which is exactly the
information a real system would have, and a good deal weaker than the latent
per-customer ``salary_day`` the simulator uses to generate the world.
"""

from __future__ import annotations

from math import cos, log10, log1p, pi, sin

import numpy as np

from kintsugi.agent.health_monitor import InferredState
from kintsugi.domain import (
    Channel, Disposition, FailureClass, Minute, Payment, Rail,
)

MINUTES_PER_DAY = 1440

_FAILURE_CLASSES = [fc for fc in FailureClass]
_DISPOSITIONS = [d for d in Disposition]
_RAILS = [r for r in Rail]
_STATES = [s for s in InferredState]


def feature_names() -> list[str]:
    names = [
        "attempt_no",
        "nudge_count",
        "log_minutes_since_last_attempt",
        "log_minutes_since_first_failure",
        "log_amount",
        "hour_sin",
        "hour_cos",
        "dom_sin",
        "dom_cos",
        "day_of_month",
        "days_to_month_start",
        "same_calendar_day_as_last_attempt",
        "calendar_days_since_last_attempt",
        "hours_until_midnight",
        "is_recurring",
        "rail_needs_customer",
        "same_cause_repeats",
        "distinct_causes_seen",
        "issuer_impaired_minutes",
    ]
    names += [f"cause_{fc.name}" for fc in _FAILURE_CLASSES]
    names += [f"disp_{d.name}" for d in _DISPOSITIONS]
    names += [f"rail_{r.name}" for r in _RAILS]
    names += [f"issuer_{s.name}" for s in _STATES]
    return names


N_FEATURES = len(feature_names())


def extract(
    payment: Payment,
    now: Minute,
    rail: Rail,
    issuer_state: InferredState = InferredState.HEALTHY,
    issuer_impaired_minutes: int = 0,
    upto_attempt: int | None = None,
    upto_nudge: int | None = None,
) -> np.ndarray:
    """Build one feature vector describing the decision state.

    ``upto_attempt`` / ``upto_nudge`` truncate the history, so training rows
    can be reconstructed from a completed run without leaking anything that
    happened after the decision being modelled.
    """
    attempts = payment.attempts if upto_attempt is None \
        else payment.attempts[:upto_attempt]
    n_nudges = payment.nudge_count if upto_nudge is None else upto_nudge

    failures = [a for a in attempts if not a.succeeded]
    last = attempts[-1] if attempts else None
    cause = last.failure_class if last and not last.succeeded else FailureClass.UNKNOWN
    if cause is None:
        cause = FailureClass.UNKNOWN

    since_last = now - (last.at if last else payment.created_at)
    first_failure_at = failures[0].at if failures else payment.created_at
    since_first = now - first_failure_at

    hour = (now // 60) % 24
    dom = (now // MINUTES_PER_DAY) % 30

    same_cause = sum(1 for a in failures if a.failure_class is cause)
    distinct = len({a.failure_class for a in failures})

    x = np.zeros(N_FEATURES, dtype=np.float32)
    i = 0
    x[i] = len(attempts); i += 1
    x[i] = n_nudges; i += 1
    x[i] = log1p(max(0, since_last)); i += 1
    x[i] = log1p(max(0, since_first)); i += 1
    x[i] = log10(max(1000, payment.amount_paise)); i += 1
    x[i] = sin(2 * pi * hour / 24); i += 1
    x[i] = cos(2 * pi * hour / 24); i += 1
    x[i] = sin(2 * pi * dom / 30); i += 1
    x[i] = cos(2 * pi * dom / 30); i += 1
    x[i] = dom; i += 1
    # Distance to the next month start, where salary credit clusters.
    x[i] = min(dom, 30 - dom); i += 1
    # Calendar-boundary features. Two of the world's mechanisms reset at
    # midnight -- daily transaction limits, and the balance draw -- so whether
    # an attempt falls on the same calendar day as the last one is decisive and
    # cannot be recovered from elapsed minutes alone: 23:50 to 00:10 is twenty
    # minutes and a completely different day. Without these the model retried
    # LIMIT_EXCEEDED failures within the same day, where they cannot succeed,
    # and scored 65.9% against a rules baseline's 92.9%.
    last_day = (last.at // MINUTES_PER_DAY) if last else (
        payment.created_at // MINUTES_PER_DAY)
    this_day = now // MINUTES_PER_DAY
    x[i] = float(this_day == last_day); i += 1
    x[i] = float(min(14, this_day - last_day)); i += 1
    x[i] = (MINUTES_PER_DAY - (now % MINUTES_PER_DAY)) / 60.0; i += 1
    x[i] = float(payment.is_recurring); i += 1
    x[i] = float(rail.requires_customer_present); i += 1
    x[i] = same_cause; i += 1
    x[i] = distinct; i += 1
    x[i] = log1p(max(0, issuer_impaired_minutes)); i += 1

    for fc in _FAILURE_CLASSES:
        x[i] = float(cause is fc); i += 1
    for d in _DISPOSITIONS:
        x[i] = float(cause.disposition is d); i += 1
    for r in _RAILS:
        x[i] = float(rail is r); i += 1
    for s in _STATES:
        x[i] = float(issuer_state is s); i += 1
    return x


# ---------------------------------------------------------------------------
# Dataset construction from completed runs
# ---------------------------------------------------------------------------


def _replay_monitor(result, monitor):
    """Replay every attempt chronologically to recover inferred issuer state.

    The monitor is causal, so replaying in time order reproduces exactly what
    it would have believed at each decision point. Snapshots are taken
    *before* folding in the current attempt -- the decision to make that
    attempt could not have used its own outcome.
    """
    events = []
    for p in result.payments:
        for a in p.attempts:
            events.append((a.at, p.payment_id, a.attempt_no, p.issuer, a))
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    snapshots: dict[tuple[str, int], tuple[InferredState, int]] = {}
    for at, pid, attempt_no, issuer, attempt in events:
        snapshots[(pid, attempt_no)] = (
            monitor.state(issuer), monitor.impaired_minutes(issuer, at))
        monitor.observe(issuer, at, attempt.succeeded, attempt.failure_class)
    return snapshots


def build_retry_dataset(result, monitor) -> tuple[np.ndarray, np.ndarray, dict]:
    """Rows: one per retry actually attempted. Label: did it authorise?"""
    snapshots = _replay_monitor(result, monitor)

    X: list[np.ndarray] = []
    y: list[int] = []
    amounts: list[int] = []

    for p in result.payments:
        # Count nudges preceding each attempt so the row reflects the true
        # state at decision time.
        for k in range(1, len(p.attempts)):
            attempt = p.attempts[k]
            state, impaired = snapshots.get(
                (p.payment_id, k), (InferredState.HEALTHY, 0))
            n_nudges = sum(1 for n in p.nudges if n.at <= attempt.at)
            X.append(extract(
                p, attempt.at, attempt.rail,
                issuer_state=state, issuer_impaired_minutes=impaired,
                upto_attempt=k, upto_nudge=n_nudges,
            ))
            y.append(int(attempt.succeeded))
            amounts.append(p.amount_paise)

    return (
        np.array(X, dtype=np.float32) if X else np.zeros((0, N_FEATURES), np.float32),
        np.array(y, dtype=np.int8),
        {"amounts": np.array(amounts, dtype=np.int64)},
    )


def build_nudge_dataset(
    result, monitor, horizon_minutes: int = 1440
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Rows: one per nudge sent. Label: did the payment recover within a day?

    Labelling on eventual recovery rather than on "did they respond" is
    deliberate. What the policy needs to value is money arriving, and a
    customer who responds enthusiastically to a reminder but still has no
    balance has produced a cost and no revenue. Under a response-based label
    the model would happily recommend nudging people who cannot pay.
    """
    snapshots = _replay_monitor(result, monitor)

    X: list[np.ndarray] = []
    y: list[int] = []
    channels: list[int] = []

    for p in result.payments:
        for j, nudge in enumerate(p.nudges):
            prior_attempts = sum(1 for a in p.attempts if a.at <= nudge.at)
            state, impaired = snapshots.get(
                (p.payment_id, max(0, prior_attempts - 1)),
                (InferredState.HEALTHY, 0))
            X.append(extract(
                p, nudge.at, p.preferred_rail,
                issuer_state=state, issuer_impaired_minutes=impaired,
                upto_attempt=prior_attempts, upto_nudge=j,
            ))
            recovered = (
                p.recovered_at is not None
                and nudge.at <= p.recovered_at <= nudge.at + horizon_minutes
            )
            y.append(int(recovered))
            channels.append(list(Channel).index(nudge.channel))

    return (
        np.array(X, dtype=np.float32) if X else np.zeros((0, N_FEATURES), np.float32),
        np.array(y, dtype=np.int8),
        {"channels": np.array(channels, dtype=np.int8)},
    )
