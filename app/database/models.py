"""
SQLAlchemy Database Models
==========================
Persists signals, historical backtests, paper trading outcomes, and research experiments.
"""

from datetime import datetime
import json
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Text,
    Enum,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class SignalRecord(Base):
    """Stores every generated signal with full causality & evidence breakdown."""
    __tablename__ = "signals"

    id = Column(String(36), primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    asset = Column(String(20), nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    strength = Column(String(20), nullable=False)
    evidence_score = Column(Integer, nullable=False)
    model_probability = Column(Float, nullable=True)
    is_ml_active = Column(Boolean, default=False)
    payout = Column(Float, nullable=False)
    breakeven_probability = Column(Float, nullable=False)
    required_probability = Column(Float, nullable=False)
    is_economically_viable = Column(Boolean, default=False)
    recommended_expiry = Column(Integer, nullable=False)
    entry_price = Column(Float, nullable=False)
    expiry_price = Column(Float, nullable=True)
    outcome = Column(String(15), default="PENDING", index=True)
    pnl = Column(Float, nullable=True)
    settled_at = Column(DateTime, nullable=True)

    # JSON Serialized metadata
    regime_json = Column(Text, nullable=True)
    evidence_json = Column(Text, nullable=True)
    strategies_json = Column(Text, nullable=True)
    feature_version = Column(String(20), default="1.0.0")
    strategy_version = Column(String(20), default="1.0.0")
    model_version = Column(String(20), default="1.0.0")


class PaperTradeRecord(Base):
    """Tracks forward-testing trades in real time on live market feeds."""
    __tablename__ = "paper_trades"

    id = Column(String(36), primary_key=True)
    signal_id = Column(String(36), nullable=False, index=True)
    asset = Column(String(20), nullable=False, index=True)
    entry_time = Column(DateTime, nullable=False)
    expiry_time = Column(DateTime, nullable=False, index=True)
    direction = Column(String(10), nullable=False)
    entry_price = Column(Float, nullable=False)
    expiry_price = Column(Float, nullable=True)
    stake = Column(Float, default=10.0)
    payout = Column(Float, default=0.85)
    outcome = Column(String(15), default="PENDING", index=True)
    pnl = Column(Float, default=0.0)
    is_settled = Column(Boolean, default=False, index=True)


class BacktestRecord(Base):
    """Summary record of historical walk-forward backtest simulations."""
    __tablename__ = "backtests"

    id = Column(String(36), primary_key=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    strategy_name = Column(String(50), nullable=False)
    asset = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    total_trades = Column(Integer, default=0)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    expected_value = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    max_loss_streak = Column(Integer, default=0)
    execution_lag_seconds = Column(Integer, default=3)
    spread_pips = Column(Float, default=1.0)
    metrics_json = Column(Text, nullable=True)


class ExperimentRecord(Base):
    """Formal tracking of research hypothesis runs and ablation results."""
    __tablename__ = "experiments"

    id = Column(String(50), primary_key=True)  # e.g., EXP-001
    timestamp = Column(DateTime, default=datetime.utcnow)
    hypothesis = Column(String(255), nullable=False)
    strategy = Column(String(50), nullable=False)
    features_used = Column(Text, nullable=False)
    train_window = Column(String(100), nullable=False)
    test_window = Column(String(100), nullable=False)
    win_rate_out_of_sample = Column(Float, default=0.0)
    ev_out_of_sample = Column(Float, default=0.0)
    config_hash = Column(String(64), nullable=False)
    result_metrics_json = Column(Text, nullable=True)
