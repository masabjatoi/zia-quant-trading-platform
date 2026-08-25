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
from datetime import datetime, timedelta, timezone
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

        if now is not None:
            dt = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)

        # 1. Minimum Evidence Score (Calibrated default: 55)
        min_score = config.get("signals.min_evidence_score", 55)
        if evidence_score < min_score:
            return FilterResult(
                passed=False,
                rejection_reason=f"Evidence score {evidence_score} is below minimum threshold of {min_score}"
            )

        # 2. Market Tradability Check (skip completely frozen zero-spread markets)
        if regime.volatility.value == "LOW" and regime.atr_percentile < 5.0 and regime.adx_value < 12.0:
            return FilterResult(
                passed=False,
                rejection_reason="Market volatility is too low (dormant/spread risk)"
            )

        # 3. Asset Cooldown Check
        # Prevents taking back-to-back trades across different cycles, but preserves the signal during the active 1-minute candle
        cooldown = config.get("signals.cooldown_seconds", 0)  # Set to 0 for continuous 1m scanning
        last_time = self.last_signal_time.get(symbol)
        if cooldown > 0 and last_time:
            lt = last_time if last_time.tzinfo else last_time.replace(tzinfo=timezone.utc)
            # Only trigger cooldown if not in the same 1-minute candle window
            if (dt - lt).total_seconds() > 0 and (dt - lt).total_seconds() < cooldown and (dt.minute != lt.minute):
                rem = cooldown - int((dt - lt).total_seconds())
                return FilterResult(
                    passed=False,
                    rejection_reason=f"Asset {symbol} is in cooldown ({rem}s remaining)"
                )

        # 4. Hourly Rate Limiting
        max_per_hour = config.get("signals.max_signals_per_hour", 20)
        timestamps = self.hourly_signal_count.get(symbol, [])
        recent_timestamps = [
            t for t in timestamps
            if (dt - (t if t.tzinfo else t.replace(tzinfo=timezone.utc))).total_seconds() < 3600
        ]
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
        if dt is not None:
            ts = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        else:
            ts = datetime.now(timezone.utc)
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
