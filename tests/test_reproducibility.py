"""
Reproducibility and Pinned Seeds Tests
"""

import pytest
import numpy as np
import pandas as pd
from app.ml.model import BinaryMLModel


def test_ml_reproducibility():
    """Confirms ML train and validation produces deterministic results given the same seed."""
    np.random.seed(42)
    n = 150
    X_df = pd.DataFrame(np.random.randn(n, 18), columns=BinaryMLModel().feature_names)
    y_series = pd.Series(np.random.choice([0, 1], size=n))

    m1 = BinaryMLModel(random_seed=42)
    metrics1, cal1 = m1.train_and_validate(X_df, y_series)

    m2 = BinaryMLModel(random_seed=42)
    metrics2, cal2 = m2.train_and_validate(X_df, y_series)

    assert metrics1["accuracy_oos"] == metrics2["accuracy_oos"]
    assert metrics1["brier_score_oos"] == metrics2["brier_score_oos"]
