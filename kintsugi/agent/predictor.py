"""Learned recovery predictors.

Two models, because the policy asks two different questions. RetryPredictor:
given this failure, now, on this rail -- would a retry authorise? NudgePredictor:
given this failure, now -- would contacting the customer get money in within a
day?

Both are gradient-boosted trees, which fit the problem: the signal is full of
interactions (INSUFFICIENT_FUNDS x day-of-month, AUTH_ABANDONED x hour,
ISSUER_DOWN x inferred issuer state) and trees find those without being told
where to look.

Calibration matters more than accuracy here. The policy doesn't consume a
classification -- it multiplies the predicted probability by an amount in rupees
and compares to a cost. A model that ranks perfectly but says 0.8 where the
truth is 0.4 will happily approve retries that lose money. So probabilities are
isotonically calibrated on a held-out split, and the evaluation reports Brier
and calibration error next to AUC, with AUC the least interesting of the three.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import train_test_split

from kintsugi.agent.features import feature_names

MODEL_DIR = Path(__file__).resolve().parents[2] / "data" / "models"


@dataclass
class ModelReport:
    name: str
    n_train: int
    n_test: int
    positive_rate: float
    auc: float
    brier: float
    brier_baseline: float
    expected_calibration_error: float
    calibration_bins: list[dict] = field(default_factory=list)

    @property
    def brier_skill_score(self) -> float:
        """Improvement over always predicting the base rate.

        A more honest headline than AUC for a probability model: it is zero for
        a model that has learned nothing useful, and negative for one that is
        actively worse than the base rate.
        """
        if self.brier_baseline <= 0:
            return 0.0
        return 1.0 - (self.brier / self.brier_baseline)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "positive_rate": self.positive_rate,
            "auc": self.auc,
            "brier": self.brier,
            "brier_baseline": self.brier_baseline,
            "brier_skill_score": self.brier_skill_score,
            "expected_calibration_error": self.expected_calibration_error,
            "calibration_bins": self.calibration_bins,
        }


class Predictor:
    """A calibrated probability model over the decision features."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = None
        self.calibrator = None
        self.report: ModelReport | None = None
        self.fallback_rate = 0.2

    # -- training --------------------------------------------------------

    def fit(
        self,
        X: np.ndarray,
        y: np.ndarray,
        test_size: float = 0.25,
        random_state: int = 0,
    ) -> ModelReport:
        if len(X) < 200 or len(np.unique(y)) < 2:
            raise ValueError(
                f"{self.name}: not enough data to fit ({len(X)} rows, "
                f"{len(np.unique(y))} classes)")

        # Three-way split: fit, calibrate, report. Calibrating on a slice the
        # booster never saw is what makes the probabilities trustworthy, and
        # reporting on a third slice keeps the calibration honest too.
        X_fit, X_hold, y_fit, y_hold = train_test_split(
            X, y, test_size=0.40, random_state=random_state, stratify=y)
        X_cal, X_te, y_cal, y_te = train_test_split(
            X_hold, y_hold, test_size=0.5, random_state=random_state,
            stratify=y_hold)

        self.model = HistGradientBoostingClassifier(
            max_iter=300,
            learning_rate=0.06,
            max_leaf_nodes=31,
            min_samples_leaf=40,
            l2_regularization=1.0,
            early_stopping=True,
            validation_fraction=0.15,
            random_state=random_state,
        )
        self.model.fit(X_fit, y_fit)

        # A single prefit isotonic map, rather than sklearn's cross-validated
        # wrapper. The wrapper trains and then *evaluates* an ensemble of four
        # boosters on every call, which is invisible while fitting and
        # crippling at decision time: the agent scores ~22 candidate
        # (moment, rail) rows per decision, tens of times per payment.
        self.calibrator = IsotonicRegression(
            y_min=0.0, y_max=1.0, out_of_bounds="clip")
        self.calibrator.fit(self.model.predict_proba(X_cal)[:, 1], y_cal)
        self.fallback_rate = float(y_fit.mean())

        p = self.predict_batch(X_te)
        base_rate = float(y_fit.mean())
        self.report = ModelReport(
            name=self.name,
            n_train=len(X_fit),
            n_test=len(X_te),
            positive_rate=float(y_te.mean()),
            auc=float(roc_auc_score(y_te, p)),
            brier=float(brier_score_loss(y_te, p)),
            brier_baseline=float(brier_score_loss(
                y_te, np.full_like(p, base_rate))),
            expected_calibration_error=_ece(y_te, p),
            calibration_bins=_calibration_bins(y_te, p),
        )
        return self.report

    # -- inference -------------------------------------------------------

    def predict(self, x: np.ndarray) -> float:
        return float(self.predict_batch(x.reshape(1, -1))[0])

    def predict_batch(self, X: np.ndarray) -> np.ndarray:
        if self.model is None:
            return np.full(len(X), self.fallback_rate)
        raw = self.model.predict_proba(X)[:, 1]
        if self.calibrator is None:
            return raw
        return self.calibrator.predict(raw)

    # -- persistence -----------------------------------------------------

    def save(self, directory: Path = MODEL_DIR) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{self.name}.pkl"
        with path.open("wb") as fh:
            pickle.dump(
                {"model": self.model, "calibrator": self.calibrator,
                 "fallback": self.fallback_rate,
                 "report": self.report.to_dict() if self.report else None,
                 "feature_names": feature_names()},
                fh,
            )
        return path

    @classmethod
    def load(cls, name: str, directory: Path = MODEL_DIR) -> "Predictor":
        path = directory / f"{name}.pkl"
        obj = cls(name)
        if not path.exists():
            return obj
        with path.open("rb") as fh:
            blob = pickle.load(fh)
        stored = blob.get("feature_names")
        if stored is not None and stored != feature_names():
            raise RuntimeError(
                f"{name}: stored model expects different features than the "
                f"current code defines. Retrain with scripts/train_predictor.py."
            )
        obj.model = blob["model"]
        obj.calibrator = blob.get("calibrator")
        obj.fallback_rate = blob["fallback"]
        return obj


def _ece(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error: mean |predicted - observed| across bins."""
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        if not mask.any():
            continue
        total += mask.mean() * abs(p[mask].mean() - y[mask].mean())
    return float(total)


def _calibration_bins(y: np.ndarray, p: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0.0, 1.0, bins + 1)
    out = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (p >= lo) & (p < hi if hi < 1.0 else p <= hi)
        if not mask.any():
            continue
        out.append({
            "bin_low": float(lo),
            "bin_high": float(hi),
            "n": int(mask.sum()),
            "predicted": float(p[mask].mean()),
            "observed": float(y[mask].mean()),
        })
    return out
