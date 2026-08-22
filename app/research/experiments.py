"""
Research Experiment Tracker
===========================
Logs and versions every quantitative experiment, parameter iteration, and ablation run.
Counts total iterations ("shots on goal") to prevent p-hacking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Any, Optional
import hashlib
import json
import uuid

from app.database.db import get_db_session
from app.database.models import ExperimentRecord


@dataclass
class ExperimentRun:
    experiment_id: str
    timestamp: datetime
    hypothesis: str
    strategy_name: str
    features: List[str]
    parameters: Dict[str, Any]
    train_window: str
    test_window: str
    win_rate_oos: float
    expected_value_oos: float
    config_hash: str
    metrics: Dict[str, Any] = field(default_factory=dict)


class ExperimentTracker:
    """Maintains an auditable log of quantitative experiments."""

    def log_experiment(
        self,
        hypothesis: str,
        strategy_name: str,
        features: List[str],
        parameters: Dict[str, Any],
        train_window: str,
        test_window: str,
        win_rate_oos: float,
        ev_oos: float,
        metrics: Optional[Dict[str, Any]] = None,
    ) -> str:
        exp_id = f"EXP-{str(uuid.uuid4())[:6].upper()}"
        now = datetime.utcnow()

        # Compute deterministic configuration hash
        param_str = json.dumps(parameters, sort_keys=True)
        config_hash = hashlib.sha256(param_str.encode("utf-8")).hexdigest()[:16]

        with get_db_session() as session:
            rec = ExperimentRecord(
                id=exp_id,
                timestamp=now,
                hypothesis=hypothesis,
                strategy=strategy_name,
                features_used=",".join(features),
                train_window=train_window,
                test_window=test_window,
                win_rate_out_of_sample=win_rate_oos,
                ev_out_of_sample=ev_oos,
                config_hash=config_hash,
                result_metrics_json=json.dumps(metrics or {}),
            )
            session.add(rec)

        return exp_id

    def list_experiments(self, limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_session() as session:
            records = session.query(ExperimentRecord).order_by(ExperimentRecord.timestamp.desc()).limit(limit).all()
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat(),
                    "hypothesis": r.hypothesis,
                    "strategy": r.strategy,
                    "features": r.features_used.split(",") if r.features_used else [],
                    "train_window": r.train_window,
                    "test_window": r.test_window,
                    "win_rate_oos": r.win_rate_out_of_sample,
                    "ev_oos": r.ev_out_of_sample,
                    "config_hash": r.config_hash,
                    "metrics": json.loads(r.result_metrics_json) if r.result_metrics_json else {}
                } for r in records
            ]
