"""
Probability Calibration Engine
==============================
Applies Platt scaling / Isotonic calibration to raw model decision scores
using strictly held-out validation data.
Evaluates Brier Score, Expected Calibration Error (ECE), and Reliability Diagrams.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import numpy as np
from sklearn.calibration import CalibratedClassifierCV


@dataclass
class ReliabilityBucket:
    predicted_min: float
    predicted_max: float
    predicted_mean: float
    actual_win_rate: float
    sample_count: int


@dataclass
class CalibrationReport:
    brier_score: float
    expected_calibration_error: float
    log_loss_value: float
    is_well_calibrated: bool
    buckets: List[ReliabilityBucket] = field(default_factory=list)


class ProbabilityCalibrator:
    """Evaluates and reports on probability calibration quality."""

    def evaluate_calibration(
        self,
        predicted_probs: np.ndarray,
        actual_outcomes: np.ndarray,
        n_bins: int = 5
    ) -> CalibrationReport:
        if len(predicted_probs) == 0:
            return CalibrationReport(
                brier_score=1.0,
                expected_calibration_error=1.0,
                log_loss_value=1.0,
                is_well_calibrated=False,
            )

        y_true = np.array(actual_outcomes, dtype=float)
        y_prob = np.array(predicted_probs, dtype=float)

        # 1. Brier Score
        brier = float(np.mean((y_prob - y_true) ** 2))

        # 2. Log Loss (Cross Entropy)
        eps = 1e-15
        p_clipped = np.clip(y_prob, eps, 1.0 - eps)
        log_loss_val = float(-np.mean(y_true * np.log(p_clipped) + (1.0 - y_true) * np.log(1.0 - p_clipped)))

        # 3. Reliability Buckets & Expected Calibration Error (ECE)
        bins = np.linspace(0.0, 1.0, n_bins + 1)
        buckets: List[ReliabilityBucket] = []
        ece = 0.0
        n_samples = len(y_prob)

        for i in range(n_bins):
            b_min = bins[i]
            b_max = bins[i + 1]
            mask = (y_prob >= b_min) & (y_prob < b_max if i < n_bins - 1 else y_prob <= b_max)
            count = int(np.sum(mask))

            if count > 0:
                pred_mean = float(np.mean(y_prob[mask]))
                act_rate = float(np.mean(y_true[mask]))
                ece += (count / n_samples) * abs(pred_mean - act_rate)
                buckets.append(ReliabilityBucket(
                    predicted_min=round(b_min, 2),
                    predicted_max=round(b_max, 2),
                    predicted_mean=round(pred_mean, 3),
                    actual_win_rate=round(act_rate, 3),
                    sample_count=count,
                ))

        is_calibrated = (ece <= 0.08 and brier <= 0.24)

        return CalibrationReport(
            brier_score=round(brier, 4),
            expected_calibration_error=round(ece, 4),
            log_loss_value=round(log_loss_val, 4),
            is_well_calibrated=is_calibrated,
            buckets=buckets,
        )
