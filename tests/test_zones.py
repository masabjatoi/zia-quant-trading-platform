"""
Unit Tests for Support/Resistance, Liquidity, Order Blocks, and FVG
"""

import pytest
from datetime import datetime, timezone, timedelta
from app.models import Candle
from app.zones.support_resistance import SupportResistanceEngine
from app.zones.liquidity import LiquidityEngine
from app.zones.order_blocks import OrderBlockEngine
from app.zones.fvg import FairValueGapEngine


def test_order_block_detection():
    engine = OrderBlockEngine()
    now = datetime.now(timezone.utc)

    # Candle 1: Normal Bullish
    c1 = Candle(now + timedelta(minutes=1), 1.0800, 1.0810, 1.0795, 1.0805)
    # Candle 2: Bearish candle (the Bullish Order Block base)
    c2 = Candle(now + timedelta(minutes=2), 1.0805, 1.0808, 1.0790, 1.0792)
    # Candle 3: Massive Bullish Displacement
    c3 = Candle(now + timedelta(minutes=3), 1.0792, 1.0840, 1.0790, 1.0838)
    # Candle 4: Continuation Bullish
    c4 = Candle(now + timedelta(minutes=4), 1.0838, 1.0860, 1.0835, 1.0858)

    blocks = engine.detect_order_blocks([c1, c2, c3, c4])
    assert len(blocks) >= 1
    bullish_obs = [b for b in blocks if b.ob_type == "BULLISH_OB"]
    assert len(bullish_obs) >= 1


def test_fvg_detection():
    engine = FairValueGapEngine()
    now = datetime.now(timezone.utc)

    # Candle 1: High at 1.0810
    c1 = Candle(now + timedelta(minutes=1), 1.0800, 1.0810, 1.0795, 1.0805)
    # Candle 2: Huge expansion
    c2 = Candle(now + timedelta(minutes=2), 1.0806, 1.0850, 1.0805, 1.0848)
    # Candle 3: Low is 1.0825 (Gap exists between c1.high 1.0810 and c3.low 1.0825)
    c3 = Candle(now + timedelta(minutes=3), 1.0845, 1.0860, 1.0825, 1.0855)

    fvgs = engine.detect_fvgs([c1, c2, c3])
    assert len(fvgs) == 1
    assert fvgs[0].fvg_type == "BULLISH_FVG"
    assert fvgs[0].gap_bottom == 1.0810
    assert fvgs[0].gap_top == 1.0825
