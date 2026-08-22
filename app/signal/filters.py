"""
Risk & Quality Filters
======================
Enforces hard guardrails:
1. Active session filter
2. Volatility health check
3. Minimum evidence score
4. Asset cooldown (prevents overtrading)
5. Consecutive loss circuit breaker
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List

from app.models import SignalDecision, SignalDirection, MultiAttributeRegime
from app.config import config


@dataclass
class FilterResult:
    passed: bool
    rejection_reason: str = ""


class RiskFilterEngine:
    """Safeguards the platform against poor market conditions and overtrading."""

    def __init__(self):
        self.last_signal_time: Dict[str, datetime] = {}
        self.consecutive_losses: Dict[str, int] = {}
        self.hourly_signal_count: Dict[str, List[datetime]] = {}

    def check_filters(
        self,
        symbol: str,
        direction: SignalDirection,
        evidence_score: int,
        regime: MultiAttributeRegime,
        now: Optional[datetime] = None,
    ) -> FilterResult:
        if direction == SignalDirection.NO_TRADE:
            return FilterResult(passed=False, rejection_reason="Direction is NO_TRADE")

        dt = now or datetime.utcnow()

        # 1. Minimum Evidence Score
        min_score = config.get("signals.min_evidence_score", 65)
        if evidence_score < min_score:
            return FilterResult(
                passed=False,
                rejection_reason=f"Evidence score {evidence_score} is below minimum threshold of {min_score}"
            )

        # 2. Market Tradability Check (skip dead/frozen markets)
        if regime.volatility.value == "LOW" and regime.atr_percentile < 10.0:
            return FilterResult(
                passed=False,
                rejection_reason="Market volatility is too low (dormant/spread risk)"
            )

        # 3. Asset Cooldown (Default: 120s between signals on same asset)
        cooldown = config.get("signals.cooldown_seconds", 120)
        last_time = self.last_signal_time.get(symbol)
        if last_time and (dt - last_time).total_seconds() < cooldown:
            rem = cooldown - int((dt - last_time).total_seconds())
            return FilterResult(
                passed=False,
                rejection_reason=f"Asset {symbol} is in cooldown ({rem}s remaining)"
            )

        # 4. Hourly Rate Limiting
        max_per_hour = config.get("signals.max_signals_per_hour", 12)
        timestamps = self.hourly_signal_count.get(symbol, [])
        recent_timestamps = [t for t in timestamps if (dt - t).total_seconds() < 3600]
        self.hourly_signal_count[symbol] = recent_timestamps
        if len(recent_timestamps) >= max_per_hour:
            return FilterResult(
                passed=False,
                rejection_reason=f"Hourly signal limit reached ({len(recent_timestamps)}/{max_per_hour})"
            )

        # 5. Consecutive Loss Circuit Breaker
        max_consec_losses = config.get("signals.max_consecutive_losses", 3)
        if self.consecutive_losses.get(symbol, 0) >= max_consec_losses:
            return FilterResult(
                passed=False,
                rejection_reason=f"Circuit breaker triggered: {self.consecutive_losses[symbol]} consecutive losses"
            )

        return FilterResult(passed=True, rejection_reason="")

    def record_signal_emitted(self, symbol: str, dt: Optional[datetime] = None) -> None:
        ts = dt or datetime.utcnow()
        self.last_signal_time[symbol] = ts
        if symbol not in self.hourly_signal_count:
            self.hourly_signal_count[symbol] = []
        self.hourly_signal_count[symbol].append(ts)

    def record_outcome(self, symbol: str, is_win: bool) -> None:
        if is_win:
            self.consecutive_losses[symbol] = 0
        else:
            self.consecutive_losses[symbol] = self.consecutive_losses.get(symbol, 0) + 1

    def reset_circuit_breaker(self, symbol: str) -> None:
        self.consecutive_losses[symbol] = 0
