"""
Liquidity Sweep Strategy (Institutional Fakeout Reversal)
=========================================================
Identifies stop-run liquidity sweeps at key swing highs/lows followed by
instant rejection and structural failure. One of the highest expectancy setups in price action.
"""

from typing import Optional
from app.models import SignalDirection, EvidenceItem
from .base import BaseStrategy, StrategyContext, StrategySignalResult
from app.zones.liquidity import LiquidityEngine
from app.zones.support_resistance import SupportResistanceEngine


class LiquidityStrategy(BaseStrategy):
    name = "LiquiditySweep"
    version = "1.0.0"
    description = "Captures institutional liquidity sweeps (stop hunts) that reject sharply back into range"
    target_regimes = []  # Can trigger in all regimes where liquidity is taken

    def __init__(self):
        self.liq_engine = LiquidityEngine()
        self.sr_engine = SupportResistanceEngine()

    def evaluate(self, ctx: StrategyContext) -> Optional[StrategySignalResult]:
        if len(ctx.candles) < 25:
            return None

        # Detect liquidity pools from preceding candles
        pools = self.liq_engine.find_liquidity_pools(ctx.candles[:-1])
        if not pools:
            return None

        # Check if the most recent candle executed a verified sweep
        sweep = self.liq_engine.detect_sweep(ctx.candles, pools)
        if not sweep:
            return None

        zones = self.sr_engine.detect_zones(ctx.candles[:-1])
        close_price = ctx.candles[-1].close
        supp, res = self.sr_engine.find_nearest_zones(close_price, zones)

        evidence = []

        # 1. Sell-Side Liquidity Sweep -> Reversal CALL
        if sweep.sweep_type == "SELL_SIDE_SWEEP":
            evidence.append(EvidenceItem(
                engine="liquidity",
                description=f"Verified Sell-Side Liquidity Sweep at {sweep.level:.5f} (Rejection Strength: {sweep.rejection_strength:.2f})",
                direction=SignalDirection.CALL,
                weight=25.0,
                confidence=0.88
            ))
            if supp and abs(close_price - supp.center_price) / close_price <= 0.002:
                evidence.append(EvidenceItem(
                    engine="zone",
                    description=f"Confluent with Support Zone ({supp.center_price:.5f})",
                    direction=SignalDirection.CALL,
                    weight=15.0,
                    confidence=0.85
                ))

            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.CALL,
                confidence=0.86,
                evidence_items=evidence,
                suggested_expiry_seconds=180,
                metadata={"sweep_level": sweep.level, "rejection_strength": sweep.rejection_strength}
            )

        # 2. Buy-Side Liquidity Sweep -> Reversal PUT
        if sweep.sweep_type == "BUY_SIDE_SWEEP":
            evidence.append(EvidenceItem(
                engine="liquidity",
                description=f"Verified Buy-Side Liquidity Sweep at {sweep.level:.5f} (Rejection Strength: {sweep.rejection_strength:.2f})",
                direction=SignalDirection.PUT,
                weight=25.0,
                confidence=0.88
            ))
            if res and abs(close_price - res.center_price) / close_price <= 0.002:
                evidence.append(EvidenceItem(
                    engine="zone",
                    description=f"Confluent with Resistance Zone ({res.center_price:.5f})",
                    direction=SignalDirection.PUT,
                    weight=15.0,
                    confidence=0.85
                ))

            return StrategySignalResult(
                strategy_name=self.name,
                direction=SignalDirection.PUT,
                confidence=0.86,
                evidence_items=evidence,
                suggested_expiry_seconds=180,
                metadata={"sweep_level": sweep.level, "rejection_strength": sweep.rejection_strength}
            )

        return None
