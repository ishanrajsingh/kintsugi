"""Fit the simulator's hazard scales to the published calibration targets.

Hand-tuning a simulator until the headline result looks good is the classic way
to produce a meaningless evaluation. So the scales are not hand-tuned: they are
solved for. Given target marginals -- per-rail authorisation rates and the
business/technical decline split from :mod:`kintsugi.calibration` -- iterative
proportional fitting adjusts each scale until the world the generator produces
reproduces those marginals.

The residuals are reported, not hidden. Where the fit does not land, the
evaluation says by how much it missed.

Run as ``python -m kintsugi.world.fitting`` to regenerate ``fitted_scales.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

from kintsugi import calibration as cal
from kintsugi.domain import FailureClass, Rail

FITTED_PATH = Path(__file__).resolve().parents[2] / "data" / "fitted_scales.json"

#: Upper bound on a fitted multiplier. Generous; exists only to stop a runaway
#: iteration, not to shape the answer.
_MAX_SCALE = 60.0


def checkout_success_target() -> float:
    """Volume-weighted authorisation rate across the checkout rail mix."""
    from kintsugi.world.simulator import _CHECKOUT_RAIL_MIX
    return sum(
        share * cal.BASE_SUCCESS_RATE[rail].v
        for rail, share in _CHECKOUT_RAIL_MIX.items()
    )


def checkout_cause_mix() -> dict[FailureClass, float]:
    """Failure-cause mix for checkout, weighted across the rail mix."""
    from kintsugi.world.simulator import _CHECKOUT_RAIL_MIX
    blended: dict[FailureClass, float] = {}
    for rail, share in _CHECKOUT_RAIL_MIX.items():
        for fc, p in cal.FAILURE_MIX[rail].v.items():
            blended[fc] = blended.get(fc, 0.0) + share * p
    total = sum(blended.values())
    return {fc: p / total for fc, p in blended.items()}


def target_absolute_rates(mandate_share: float) -> dict[FailureClass, float]:
    """Target P(first attempt fails with cause) across the whole population."""
    chk_fail = 1.0 - checkout_success_target()
    mand_fail = 1.0 - cal.RECURRING_MANDATE_SUCCESS_RATE.v

    chk_mix = checkout_cause_mix()
    mand_mix = cal.MANDATE_FAILURE_MIX.v

    targets: dict[FailureClass, float] = {}
    for fc in FailureClass:
        if fc is FailureClass.UNKNOWN:
            continue
        targets[fc] = (
            (1 - mandate_share) * chk_fail * chk_mix.get(fc, 0.0)
            + mandate_share * mand_fail * mand_mix.get(fc, 0.0)
        )
    return targets


def measure(world) -> dict:
    """First-attempt outcomes, split by segment.

    Measured on the *initial* authorisation only. Retry behaviour is a
    consequence of policy, so including it would make the calibration depend
    on whichever policy happened to be running.
    """
    counts = {"checkout": {}, "mandate": {}}
    ok_n = {"checkout": 0, "mandate": 0}
    tot_n = {"checkout": 0, "mandate": 0}

    for p in world._template:
        seg = "mandate" if world._is_mandate(p) else "checkout"
        ok, cause = world.resolve_attempt(p, p.preferred_rail, p.created_at, 0)
        tot_n[seg] += 1
        if ok:
            ok_n[seg] += 1
        else:
            counts[seg][cause] = counts[seg].get(cause, 0) + 1

    rates = {
        seg: {fc: c / max(1, tot_n[seg]) for fc, c in counts[seg].items()}
        for seg in counts
    }
    n = len(world._template)
    return {
        "rates": rates,
        "counts": counts,
        "n_by_segment": tot_n,
        "checkout_success": ok_n["checkout"] / max(1, tot_n["checkout"]),
        "mandate_success": ok_n["mandate"] / max(1, tot_n["mandate"]),
        "overall_success": sum(ok_n.values()) / max(1, n),
        "n": n,
    }


def segment_targets() -> dict[str, dict[FailureClass, float]]:
    """Per-segment target P(first attempt fails with cause).

    Each segment carries its own published authorisation rate and its own
    published cause mix, so each gets its own target vector. This is the
    formulation that makes the fit well posed.
    """
    chk_fail = 1.0 - checkout_success_target()
    mand_fail = 1.0 - cal.RECURRING_MANDATE_SUCCESS_RATE.v
    chk_mix = checkout_cause_mix()
    mand_mix = cal.MANDATE_FAILURE_MIX.v
    return {
        "checkout": {fc: chk_fail * p for fc, p in chk_mix.items() if p > 0},
        "mandate": {fc: mand_fail * p for fc, p in mand_mix.items() if p > 0},
    }


def fit_scales(
    config,
    iterations: int = 60,
    damping: float = 0.55,
    verbose: bool = True,
) -> tuple[dict, dict]:
    """Fit per-segment hazard scales by iterative proportional fitting.

    Each segment is fitted against its own target vector, measured only on that
    segment's payments. Because the two segments no longer share a scale, both
    published authorisation rates and both published cause mixes can be
    satisfied simultaneously, and the fit no longer runs onto its bounds.

    Nothing here is tuned toward a recovery result. The objective is entirely
    "reproduce the published marginals"; the agent is evaluated afterwards
    against whatever world that produces.
    """
    from kintsugi.world.simulator import DEFAULT_HAZARD_SCALES, World

    targets = segment_targets()
    scales = {
        "checkout": DEFAULT_HAZARD_SCALES.copy(),
        "mandate": DEFAULT_HAZARD_SCALES.copy(),
    }
    world = World(config, hazard_scales=scales)

    for it in range(iterations):
        world.hazard_scales = scales
        stats = measure(world)
        for seg, seg_targets in targets.items():
            achieved = stats["rates"][seg]
            for fc, target in seg_targets.items():
                if target <= 0:
                    continue
                got = achieved.get(fc, 0.0)
                if got <= 1e-9:
                    scales[seg][fc] *= 1.7      # never fired; open it up
                    continue
                scales[seg][fc] *= (target / got) ** damping
                # Scales are multipliers, not probabilities: they legitimately
                # exceed 1 where the shaping term is small (a mandate balance
                # gate). Probabilities are clamped at each gate instead.
                scales[seg][fc] = min(_MAX_SCALE, max(1e-9, scales[seg][fc]))

        if verbose and (it % 15 == 0 or it == iterations - 1):
            err = max(_max_rel_error(targets[s], stats["rates"][s]) for s in targets)
            print(f"  iter {it:2d}  checkout={stats['checkout_success']:.4f} "
                  f"mandate={stats['mandate_success']:.4f}  max_rel_err={err:.4f}")

    world.hazard_scales = scales
    return scales, measure(world)


def _max_rel_error(targets: dict, achieved: dict) -> float:
    worst = 0.0
    for fc, t in targets.items():
        if t <= 1e-6:
            continue
        got = achieved.get(fc, 0.0)
        worst = max(worst, abs(got - t) / t)
    return worst


def _tech_share(rates: dict, tech: set) -> float:
    total = sum(rates.values())
    return sum(v for fc, v in rates.items() if fc in tech) / total if total else 0.0


def fit_report(config, scales: dict, stats: dict) -> dict:
    """Target vs achieved, for publication in the evaluation report."""
    targets = segment_targets()
    tech = {FailureClass.ISSUER_DOWN, FailureClass.PSP_TIMEOUT,
            FailureClass.NETWORK_TIMEOUT}

    all_fail = {}
    for seg, rates in stats["rates"].items():
        w = stats["n_by_segment"][seg] / max(1, stats["n"])
        for fc, r in rates.items():
            all_fail[fc] = all_fail.get(fc, 0.0) + w * r
    total_fail = sum(all_fail.values())
    tech_share = (sum(v for fc, v in all_fail.items() if fc in tech) / total_fail
                  if total_fail else 0.0)

    causes = []
    for seg, seg_targets in targets.items():
        achieved = stats["rates"][seg]
        for fc, tgt in sorted(seg_targets.items(), key=lambda kv: -kv[1]):
            got = achieved.get(fc, 0.0)
            causes.append({
                "segment": seg,
                "cause": fc.name,
                "target": tgt,
                "achieved": got,
                "rel_error": abs(got - tgt) / tgt if tgt > 1e-9 else 0.0,
            })

    return {
        "checkout_success": {
            "target": checkout_success_target(),
            "achieved": stats["checkout_success"],
            "published_band": [0.85, 0.95],
        },
        "mandate_success": {
            "target": cal.RECURRING_MANDATE_SUCCESS_RATE.v,
            "achieved": stats["mandate_success"],
            "published_band": [0.30, 0.50],
        },
        "technical_decline_share": {
            "target": 1.0 - cal.BD_SHARE_OF_FAILURES.v,
            "achieved_blended": tech_share,
            "achieved_checkout_only": _tech_share(stats["rates"]["checkout"], tech),
            "note": (
                "The published 81.7/18.3 business-technical split is measured "
                "across all digital transactions, which are overwhelmingly "
                "customer-initiated. The comparable figure here is therefore "
                "the checkout-only share. The blended number sits lower purely "
                "because this world carries a 30% mandate segment, and mandate "
                "failures are dominated by balance -- a business decline."
            ),
        },
        "causes": causes,
        "max_rel_error": max(
            _max_rel_error(targets[s], stats["rates"][s]) for s in targets),
    }


def load_fitted() -> tuple[dict[FailureClass, float], dict] | tuple[None, None]:
    """Load committed parameters so results reproduce without re-fitting."""
    if not FITTED_PATH.exists():
        return None, None
    raw = json.loads(FITTED_PATH.read_text())
    scales = {
        seg: {FailureClass[k]: v for k, v in per_seg.items()}
        for seg, per_seg in raw["scales"].items()
    }
    return scales, raw.get("segment_params", {})


def main() -> None:
    from kintsugi.world.simulator import WorldConfig

    cfg = WorldConfig(n_customers=6_000, n_payments=40_000, seed=101)
    print("Fitting hazard scales to published calibration targets...")
    scales, stats = fit_scales(cfg)
    report = fit_report(cfg, scales, stats)
    segment = {"checkout_selection_bonus": 0.62}

    FITTED_PATH.parent.mkdir(parents=True, exist_ok=True)
    FITTED_PATH.write_text(json.dumps({
        "scales": {
            seg: {fc.name: round(v, 8) for fc, v in per_seg.items()}
            for seg, per_seg in scales.items()
        },
        "segment_params": {k: round(v, 6) for k, v in segment.items()},
        "fit_report": report,
        "fit_config": {
            "n_payments": cfg.n_payments,
            "n_customers": cfg.n_customers,
            "seed": cfg.seed,
            "mandate_share": cfg.mandate_share,
        },
    }, indent=2))

    print(f"\nWrote {FITTED_PATH}")
    print(f"\n  checkout success  target {report['checkout_success']['target']:.4f}"
          f"  achieved {report['checkout_success']['achieved']:.4f}")
    print(f"  mandate success   target {report['mandate_success']['target']:.4f}"
          f"  achieved {report['mandate_success']['achieved']:.4f}"
          f"  (published band 0.30-0.50)")
    ts = report["technical_decline_share"]
    print(f"  technical share   target {ts['target']:.4f}"
          f"  achieved {ts['achieved_checkout_only']:.4f} (checkout-only,"
          f" comparable)  {ts['achieved_blended']:.4f} (blended)")
    print(f"  max relative error across causes: {report['max_rel_error']:.3f}")


if __name__ == "__main__":
    main()
