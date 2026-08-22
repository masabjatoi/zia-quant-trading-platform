"""
Domain Models
=============
Strictly typed data structures for candles, evidence, market structure,
signals, backtesting, and validation reports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any


class SignalDirection(str, Enum):
    CALL = "CALL"
    PUT = "PUT"
    NO_TRADE = "NO_TRADE"


class SignalStrength(str, Enum):
    STRONG = "STRONG"       # Evidence score >= 80 & multi-engine convergence
    MODERATE = "MODERATE"   # Evidence score 65-79
    WEAK = "WEAK"           # Evidence score 50-64
    NO_TRADE = "NO_TRADE"   # Below threshold or conflicting filters


class MarketTrend(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    TRANSITION = "TRANSITION"


class MarketVolatility(str, Enum):
    HIGH = "HIGH"
    NORMAL = "NORMAL"
    LOW = "LOW"


class MarketStructureType(str, Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    BREAKOUT = "BREAKOUT"
    TRANSITION = "TRANSITION"


class TradeOutcome(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    TIE = "TIE"
    PENDING = "PENDING"


class DataQualityStatus(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL_MOVE = "ABNORMAL_MOVE"
    NEWS_SPIKE = "NEWS_SPIKE"
    DATA_ERROR = "DATA_ERROR"
    GAP = "GAP"


@dataclass(frozen=True)
class Candle:
    """Immutable OHLCV candle."""
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    timeframe: str = "1m"

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def total_range(self) -> float:
        return self.high - self.low

    @property
    def body_ratio(self) -> float:
        if self.total_range <= 1e-9:
            return 0.0
        return self.body / self.total_range

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def is_doji(self) -> bool:
        return self.body_ratio < 0.10 and self.total_range > 0


@dataclass
class EvidenceItem:
    """A single piece of traceable evidence."""
    engine: str          # e.g., "structure", "liquidity", "zone", "momentum", "trend"
    description: str     # human readable explanation
    direction: SignalDirection
    weight: float        # contribution points (positive for match, negative for penalty)
    confidence: float    # 0.0 to 1.0


@dataclass
class MultiAttributeRegime:
    """Multi-attribute regime classification to avoid oversimplifying market state."""
    trend: MarketTrend = MarketTrend.NEUTRAL
    volatility: MarketVolatility = MarketVolatility.NORMAL
    structure: MarketStructureType = MarketStructureType.RANGING
    session: str = "OFF_HOURS"
    adx_value: float = 0.0
    atr_value: float = 0.0
    atr_percentile: float = 50.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trend": self.trend.value,
            "volatility": self.volatility.value,
            "structure": self.structure.value,
            "session": self.session,
            "adx": round(self.adx_value, 2),
            "atr": round(self.atr_value, 5),
            "atr_percentile": round(self.atr_percentile, 1),
        }


@dataclass
class SignalDecision:
    """
    Complete signal with 3-tier confidence breakdown and full causality metadata.
    """
    id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    asset: str = ""
    direction: SignalDirection = SignalDirection.NO_TRADE
    strength: SignalStrength = SignalStrength.NO_TRADE

    # Tier 1: Technical Evidence Score (0 - 100)
    evidence_score: int = 0
    evidence_list: List[EvidenceItem] = field(default_factory=list)

    # Tier 2: Model Calibrated Probability (0.0 - 1.0)
    model_probability: Optional[float] = None
    is_ml_active: bool = False  # False until validated on out-of-sample data

    # Tier 3: Economic Viability
    payout: float = 0.85
    breakeven_probability: float = 0.5405
    required_probability: float = 0.5905
    is_economically_viable: bool = False

    # Execution Parameters
    recommended_expiry: int = 300  # seconds
    entry_price: float = 0.0
    regime: MultiAttributeRegime = field(default_factory=MultiAttributeRegime)
    strategies_fired: List[str] = field(default_factory=list)

    # Version Tracking
    feature_version: str = "1.0.0"
    strategy_version: str = "1.0.0"
    model_version: str = "1.0.0"

    # Outcome tracking (filled by outcome settlement engine at T + expiry)
    expiry_price: Optional[float] = None
    outcome: TradeOutcome = TradeOutcome.PENDING
    settled_at: Optional[datetime] = None
    pnl: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "asset": self.asset,
            "direction": self.direction.value,
            "strength": self.strength.value,
            "evidence_score": self.evidence_score,
            "model_probability": round(self.model_probability, 3) if self.model_probability is not None else None,
            "is_ml_active": self.is_ml_active,
            "payout": self.payout,
            "breakeven_probability": round(self.breakeven_probability, 3),
            "required_probability": round(self.required_probability, 3),
            "is_economically_viable": self.is_economically_viable,
            "recommended_expiry": self.recommended_expiry,
            "entry_price": self.entry_price,
            "regime": self.regime.to_dict(),
            "strategies_fired": self.strategies_fired,
            "evidence": [
                {
                    "engine": e.engine,
                    "description": e.description,
                    "direction": e.direction.value,
                    "weight": round(e.weight, 1),
                    "confidence": round(e.confidence, 2)
                } for e in self.evidence_list
            ],
            "outcome": self.outcome.value,
            "expiry_price": self.expiry_price,
            "pnl": self.pnl
        }


@dataclass
class BacktestTrade:
    """Individual trade executed during backtesting with lag and spread."""
    trade_id: str
    asset: str
    signal_time: datetime
    execution_time: datetime
    expiry_time: datetime
    direction: SignalDirection
    signal_price: float
    entry_price: float      # price after execution lag & spread
    expiry_price: float
    expiry_seconds: int
    payout: float
    outcome: TradeOutcome
    pnl: float
    evidence_score: int
    model_probability: Optional[float]
    regime: MultiAttributeRegime


@dataclass
class BacktestReport:
    """Comprehensive performance report with binary-specific metrics."""
    strategy_name: str
    asset: str
    timeframe: str
    start_date: datetime
    end_date: datetime
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    ties: int = 0
    win_rate: float = 0.0
    payout: float = 0.85
    breakeven_winrate: float = 0.5405
    expected_value_per_trade: float = 0.0
    total_pnl: float = 0.0
    max_consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    profit_factor: float = 0.0
    brier_score: Optional[float] = None
    trades: List[BacktestTrade] = field(default_factory=list)

    def calculate_stats(self) -> None:
        self.total_trades = len(self.trades)
        if self.total_trades == 0:
            return

        self.wins = sum(1 for t in self.trades if t.outcome == TradeOutcome.WIN)
        self.losses = sum(1 for t in self.trades if t.outcome == TradeOutcome.LOSS)
        self.ties = sum(1 for t in self.trades if t.outcome == TradeOutcome.TIE)
        decisive_trades = self.wins + self.losses

        if decisive_trades > 0:
            self.win_rate = self.wins / decisive_trades
            self.expected_value_per_trade = (
                self.win_rate * self.payout - (1.0 - self.win_rate) * 1.0
            )

        self.total_pnl = sum(t.pnl for t in self.trades)

        total_win_pnl = sum(t.pnl for t in self.trades if t.pnl > 0)
        total_loss_pnl = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        self.profit_factor = (total_win_pnl / total_loss_pnl) if total_loss_pnl > 0 else 99.0

        # Streaks
        cur_win, cur_loss = 0, 0
        for t in self.trades:
            if t.outcome == TradeOutcome.WIN:
                cur_win += 1
                cur_loss = 0
                self.max_consecutive_wins = max(self.max_consecutive_wins, cur_win)
            elif t.outcome == TradeOutcome.LOSS:
                cur_loss += 1
                cur_win = 0
                self.max_consecutive_losses = max(self.max_consecutive_losses, cur_loss)
            else:
                cur_win = 0
                cur_loss = 0
