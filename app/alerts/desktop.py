"""
Desktop Notification Dispatcher
===============================
Broadcaster for local notifications and terminal audio alerts.
"""

from typing import Optional
from app.models import SignalDecision, SignalDirection


class DesktopAlertDispatcher:
    """Delivers local desktop sound and visual alerts."""

    def notify(self, sig: SignalDecision) -> None:
        if sig.direction == SignalDirection.NO_TRADE:
            return

        direction_str = "CALL ▲" if sig.direction == SignalDirection.CALL else "PUT ▼"
        title = f"Quotex Alert: {sig.asset} {direction_str}"
        msg = f"Score: {sig.evidence_score}/100 | Expiry: {sig.recommended_expiry // 60}m | Price: {sig.entry_price:.5f}"

        # Standard console notification
        print(f"\n🔔 [ALERT] {title} - {msg}\n")
