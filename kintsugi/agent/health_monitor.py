"""Detect issuer outages from the attempt stream alone.

No privileged access: this sees what a gateway sees, a stream of authorisation
outcomes per issuer, and has to work out that a bank is failing without crying
wolf.

We watch the *technical decline rate* per issuer, not the overall success rate.
Overall success rate doesn't work -- with a decent recurring book baseline
failure is ~25% because mandates bounce on balance, and that noise buries the
outage signal (recall came out at 1.3%). Technical decline separates cleanly:
0.7% healthy, 11.9% degraded, 49.6% outage. It's also what NPCI publishes per
bank, and what an ops team actually watches.

Detection is a one-sided CUSUM on the Bernoulli log-likelihood ratio: failures
push the statistic up, successes pull it down, alarm on threshold. CUSUM rather
than a rolling window because detection *delay* is what costs money, and a
30-minute average is still half healthy traffic when the bank has been down for
fifteen.

Two things that bite if you skip them: freeze the baseline while alarmed (or it
chases the outage down and silently clears), and require sustained recovery to
clear (flapping is worse than being slow, since a policy that trusts it retries
straight back into the outage).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from math import log

from kintsugi.domain import FailureClass


#: Failure causes that indicate infrastructure trouble rather than anything
#: about the customer. Resolved by the taxonomy layer from the raw gateway text.
_TECHNICAL_CLASSES = frozenset({
    FailureClass.ISSUER_DOWN,
    FailureClass.PSP_TIMEOUT,
    FailureClass.NETWORK_TIMEOUT,
})


class InferredState(Enum):
    """What the monitor believes, as distinct from what is true."""

    HEALTHY = auto()
    SUSPECTED_DEGRADED = auto()
    SUSPECTED_OUTAGE = auto()

    @property
    def is_impaired(self) -> bool:
        return self is not InferredState.HEALTHY


@dataclass(slots=True)
class IssuerBelief:
    """Online belief about one issuer."""

    baseline_technical: float = 0.012
    """EWMA of the healthy-period technical decline rate."""

    observations: int = 0
    cusum: float = 0.0
    recovery_cusum: float = 0.0
    state: InferredState = InferredState.HEALTHY
    alarm_since: int | None = None
    recent_technical: int = 0
    recent_total: int = 0

    #: Attempts seen since the alarm fired; used to gate clearing on evidence
    #: rather than on elapsed time alone.
    since_alarm: int = 0

    def observed_rate(self) -> float:
        """Recent technical decline rate."""
        return (self.recent_technical / self.recent_total
                if self.recent_total else self.baseline_technical)


class IssuerHealthMonitor:
    """CUSUM change detection over per-issuer authorisation outcomes."""

    def __init__(
        self,
        impaired_technical_rate: float = 0.25,
        alarm_threshold: float = 8.0,
        outage_threshold: float = 15.0,
        clear_threshold: float = 3.5,
        baseline_alpha: float = 0.004,
        min_observations: int = 25,
        warmup_baseline: float = 0.012,
    ) -> None:
        self.impaired_technical_rate = impaired_technical_rate
        """Technical decline rate under the impaired hypothesis."""

        self.alarm_threshold = alarm_threshold
        """Chosen by sweeping thresholds on tuning seeds (11-13) and evaluating
        on disjoint seeds, so the reported numbers are not the ones the
        threshold was picked on.

        The operating point is deliberately precision-heavy. The costs are
        badly asymmetric: a false alarm makes the policy stop retrying a
        *healthy* issuer, losing revenue on every payment routed there, while a
        missed detection merely degrades the agent to baseline behaviour on
        that incident. At threshold 4.0 this detector reached 33% recall at 42%
        precision; at 8.0 it holds ~93% precision. The second is the one worth
        shipping, and the first is the one that looks better in a slide."""

        self.outage_threshold = outage_threshold
        self.clear_threshold = clear_threshold
        self.baseline_alpha = baseline_alpha
        self.min_observations = min_observations
        self.warmup_baseline = warmup_baseline
        self._cusum_cap = outage_threshold * 2.0
        self.beliefs: dict[str, IssuerBelief] = {}
        self.alarms: list[dict] = []
        """Every alarm raised, for scoring against ground truth afterwards."""

    def reset(self) -> None:
        self.beliefs.clear()
        self.alarms.clear()

    def _belief(self, issuer: str) -> IssuerBelief:
        b = self.beliefs.get(issuer)
        if b is None:
            b = IssuerBelief(baseline_technical=self.warmup_baseline)
            self.beliefs[issuer] = b
        return b

    def observe(
        self,
        issuer: str,
        at: int,
        succeeded: bool,
        failure_class=None,
    ) -> None:
        """Fold one authorisation outcome into the belief for its issuer.

        Only the *classified* outcome is used, never the simulator's latent
        health. ``failure_class`` is whatever the taxonomy layer resolved the
        raw gateway string to.
        """
        technical = (not succeeded) and failure_class in _TECHNICAL_CLASSES

        b = self._belief(issuer)
        b.observations += 1
        b.recent_total += 1
        b.recent_technical += int(technical)

        # Decay the short-run counters so `observed_rate` tracks the present.
        if b.recent_total > 400:
            b.recent_total //= 2
            b.recent_technical //= 2

        # Learn the healthy baseline only while we believe things are healthy.
        # Updating during an outage would let the baseline follow the failure
        # up and quietly silence the alarm.
        if b.state is InferredState.HEALTHY:
            b.baseline_technical += self.baseline_alpha * (
                float(technical) - b.baseline_technical)
            b.baseline_technical = min(0.30, max(0.002, b.baseline_technical))

        if b.observations < self.min_observations:
            return

        p0 = b.baseline_technical
        p1 = max(p0 * 3.0, self.impaired_technical_rate)
        p1 = min(0.95, p1)

        if technical:
            llr = log(p1 / p0)
        else:
            llr = log((1.0 - p1) / (1.0 - p0))

        # Cap the statistic. An uncapped CUSUM keeps accumulating for as long
        # as an incident lasts, so a two-hour outage banks so much evidence
        # that it then takes hundreds of healthy attempts to decay back below
        # the threshold -- the alarm stays stuck on long after the bank
        # recovered, and the policy keeps refusing to route to a healthy
        # issuer. Capping bounds the clear time independently of how long the
        # incident ran.
        b.cusum = min(self._cusum_cap, max(0.0, b.cusum + llr))
        # Mirror statistic: accumulates evidence that we are back to healthy.
        b.recovery_cusum = max(0.0, b.recovery_cusum - llr)

        if b.state.is_impaired:
            b.since_alarm += 1

        self._transition(issuer, b, at)

    def _transition(self, issuer: str, b: IssuerBelief, at: int) -> None:
        previous = b.state

        # Recovery is checked *first*, and on its own dedicated statistic.
        # Waiting for the alarm statistic to decay below the raise threshold
        # would make the clear time depend on incident length rather than on
        # evidence that the issuer is healthy again.
        if b.state.is_impaired and b.recovery_cusum >= self.clear_threshold:
            b.state = InferredState.HEALTHY
            b.cusum = 0.0
            b.recovery_cusum = 0.0
            b.since_alarm = 0
            if self.alarms and self.alarms[-1]["issuer"] == issuer \
                    and self.alarms[-1].get("cleared_at") is None:
                self.alarms[-1]["cleared_at"] = at
        elif b.cusum >= self.outage_threshold:
            b.state = InferredState.SUSPECTED_OUTAGE
        elif b.cusum >= self.alarm_threshold:
            b.state = InferredState.SUSPECTED_DEGRADED

        if previous is InferredState.HEALTHY and b.state.is_impaired:
            b.alarm_since = at
            b.recovery_cusum = 0.0
            self.alarms.append({
                "issuer": issuer,
                "raised_at": at,
                "cleared_at": None,
                "state": b.state.name,
            })
        elif previous.is_impaired and b.state is InferredState.SUSPECTED_OUTAGE \
                and self.alarms and self.alarms[-1].get("cleared_at") is None:
            self.alarms[-1]["state"] = b.state.name

    # -- what the policy asks --------------------------------------------

    def state(self, issuer: str) -> InferredState:
        b = self.beliefs.get(issuer)
        return b.state if b else InferredState.HEALTHY

    def is_impaired(self, issuer: str) -> bool:
        return self.state(issuer).is_impaired

    def success_multiplier(self, issuer: str) -> float:
        """Belief about how much this issuer is currently depressing success.

        Used directly by the expected-value policy: retrying into a suspected
        outage has its success probability scaled by this.
        """
        state = self.state(issuer)
        if state is InferredState.SUSPECTED_OUTAGE:
            return 0.15
        if state is InferredState.SUSPECTED_DEGRADED:
            return 0.55
        return 1.0

    def impaired_minutes(self, issuer: str, now: int) -> int:
        b = self.beliefs.get(issuer)
        if b is None or not b.state.is_impaired or b.alarm_since is None:
            return 0
        return now - b.alarm_since


# ---------------------------------------------------------------------------
# Scoring the detector against ground truth
# ---------------------------------------------------------------------------


@dataclass
class DetectionScore:
    true_incidents: int
    detected: int
    false_alarms: int
    latencies: list[int] = field(default_factory=list)
    by_duration: dict = field(default_factory=dict)

    @property
    def recall(self) -> float:
        return self.detected / self.true_incidents if self.true_incidents else 0.0

    @property
    def precision(self) -> float:
        total = self.detected + self.false_alarms
        return self.detected / total if total else 0.0

    @property
    def median_latency(self) -> float:
        if not self.latencies:
            return float("nan")
        s = sorted(self.latencies)
        mid = len(s) // 2
        return float(s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2)

    def to_dict(self) -> dict:
        return {
            "true_incidents": self.true_incidents,
            "detected": self.detected,
            "false_alarms": self.false_alarms,
            "recall": self.recall,
            "precision": self.precision,
            "median_detection_latency_min": self.median_latency,
            "recall_by_incident_duration": self.by_duration,
        }


def score_detection(
    monitor: IssuerHealthMonitor,
    registry,
    min_incident_minutes: int = 20,
    grace_minutes: int = 10,
) -> DetectionScore:
    """Compare raised alarms against the simulator's true incident intervals.

    Two different denominators, deliberately.

    **Precision** matches alarms against *every* true incident regardless of
    duration. An alarm raised during a genuine twelve-minute outage is a
    correct detection, and scoring it as a false positive because the incident
    was too short to appear in the recall denominator would understate the
    detector badly. (It did, in an earlier version of this function: precision
    read 42% when most of the supposed false alarms were real incidents.)

    **Recall** is computed only over incidents long enough that the issuer saw
    meaningful traffic during them. A four-minute outage on a low-volume issuer
    may generate no attempts at all, and scoring a detector on events it had no
    opportunity to observe measures the traffic pattern, not the detector.

    A short grace window after an incident ends still counts as attributable:
    a sequential detector necessarily lags the change it is detecting, so an
    alarm that fires just after recovery was still caused by the real event.
    """
    all_intervals: dict[str, list[tuple[int, int]]] = {}
    scorable: dict[str, list[tuple[int, int]]] = {}
    scorable_total = 0

    for code, timeline in registry.timelines.items():
        spans = [(iv.start, iv.end) for iv in timeline.incidents()]
        all_intervals[code] = spans
        long_spans = [s for s in spans if s[1] - s[0] >= min_incident_minutes]
        scorable[code] = long_spans
        scorable_total += len(long_spans)

    detected_spans: set[tuple[str, int, int]] = set()
    false_alarms = 0
    latencies: list[int] = []
    by_duration: dict[str, list[int]] = {}

    for alarm in monitor.alarms:
        issuer, raised = alarm["issuer"], alarm["raised_at"]
        match = None
        for start, end in all_intervals.get(issuer, []):
            if start <= raised <= end + grace_minutes:
                match = (start, end)
                break
        if match is None:
            false_alarms += 1
            continue
        key = (issuer, *match)
        if key not in detected_spans:
            detected_spans.add(key)
            if match in scorable.get(issuer, []):
                latencies.append(max(0, raised - match[0]))

    detected_scorable = sum(
        1 for (issuer, start, end) in detected_spans
        if (start, end) in scorable.get(issuer, [])
    )

    # Recall stratified by incident length: the long incidents are the ones
    # that actually cost money, so they are the ones worth being judged on.
    strata = {"20-45min": (20, 45), "45-90min": (45, 90), "90min+": (90, 10 ** 9)}
    by_duration = {}
    for label, (lo, hi) in strata.items():
        total = hit = 0
        for code, spans in scorable.items():
            for s in spans:
                if lo <= s[1] - s[0] < hi:
                    total += 1
                    hit += (code, *s) in detected_spans
        by_duration[label] = {
            "incidents": total,
            "detected": hit,
            "recall": hit / total if total else float("nan"),
        }

    return DetectionScore(
        true_incidents=scorable_total,
        detected=detected_scorable,
        false_alarms=false_alarms,
        latencies=latencies,
        by_duration=by_duration,
    )
