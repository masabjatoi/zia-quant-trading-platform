"""
Machine Learning Predictive Model
=================================
Gradient Boosting Classifier trained on chronological backtest feature data.
Uses strict train -> validation (calibration) -> test out-of-sample splits.
"""

from typing import Tuple, Optional, Dict, Any
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.calibration import CalibratedClassifierCV

from .features import MLFeatureExtractor
from .calibration import ProbabilityCalibrator, CalibrationReport
from app.config import config


class BinaryMLModel:
    """Predicts trade win probability with calibrated probabilities."""

    def __init__(self, random_seed: int = 42):
        self.seed = random_seed
        self.feature_extractor = MLFeatureExtractor()
        self.calibrator = ProbabilityCalibrator()
        self.model: Optional[CalibratedClassifierCV] = None
        self.is_trained: bool = False
        self.feature_names = self.feature_extractor.FEATURE_NAMES

    def train_and_validate(
        self,
        X_df: pd.DataFrame,
        y_series: pd.Series,
        train_pct: float = 0.60,
        val_pct: float = 0.20
    ) -> Tuple[Dict[str, Any], CalibrationReport]:
        """
        Chronological split:
        [ Train (0 to 60%) ] -> [ Validation for Calibration (60% to 80%) ] -> [ Test OOS (80% to 100%) ]
        """
        n = len(X_df)
        if n < 50:
            return {"error": "Insufficient labeled samples (minimum 50 required)"}, CalibrationReport(1.0, 1.0, 1.0, False)

        i_train = int(n * train_pct)
        i_val = int(n * (train_pct + val_pct))

        X_train, y_train = X_df.iloc[:i_train].values, y_series.iloc[:i_train].values
        X_val, y_val = X_df.iloc[i_train:i_val].values, y_series.iloc[i_train:i_val].values
        X_test, y_test = X_df.iloc[i_val:].values, y_series.iloc[i_val:].values

        # 1. Train Base Gradient Boosting Classifier with fixed seed
        base_clf = GradientBoostingClassifier(
            n_estimators=40,
            learning_rate=0.05,
            max_depth=3,
            random_state=self.seed
        )

        # 2. Fit Calibrated Classifier on Train + Val splits
        calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method="sigmoid", cv=2)
        X_train_val = np.vstack([X_train, X_val])
        y_train_val = np.concatenate([y_train, y_val])
        calibrated_clf.fit(X_train_val, y_train_val)
        self.model = calibrated_clf
        self.is_trained = True

        # 3. Evaluate Out-of-Sample on Test Split
        test_probs = calibrated_clf.predict_proba(X_test)[:, 1]
        cal_report = self.calibrator.evaluate_calibration(test_probs, y_test)

        test_preds = (test_probs >= 0.50).astype(int)
        accuracy_oos = float(np.mean(test_preds == y_test))

        metrics = {
            "total_samples": n,
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "test_samples": len(X_test),
            "accuracy_oos": round(accuracy_oos, 4),
            "brier_score_oos": cal_report.brier_score,
            "ece_oos": cal_report.expected_calibration_error,
            "is_calibrated": cal_report.is_well_calibrated
        }

        return metrics, cal_report

    def predict_probability(self, df_enriched: pd.DataFrame) -> Optional[float]:
        """Predicts calibrated win probability for the current candle."""
        if not self.is_trained or self.model is None:
            return None

        feats = self.feature_extractor.extract_single_row(df_enriched)
        try:
            probs = self.model.predict_proba(feats)
            win_prob = float(probs[0, 1])
            return round(win_prob, 3)
        except Exception:
            return None
