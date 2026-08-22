"""
Telegram Alert Dispatcher
=========================
Formats institutional signal alerts with 3-tier confidence, market regime,
and traceable evidence points customized for Zia.
"""

from typing import Optional
import requests
from app.models import SignalDecision, SignalDirection


class TelegramAlertDispatcher:
    """Dispatches high-conviction signals to Telegram for Zia."""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = bot_token
        self.chat_id = chat_id

    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send_signal(self, sig: SignalDecision) -> bool:
        if not self.is_configured() or sig.direction == SignalDirection.NO_TRADE:
            return False

        emoji_dir = "🟢 CALL (HIGHER)" if sig.direction == SignalDirection.CALL else "🔴 PUT (LOWER)"
        evidence_lines = "\n".join([f"  • {e.description}" for e in sig.evidence_list[:4]])

        msg = (
            f"⚡ <b>ZIA QUANT — QUOTEX BINARY SIGNAL</b> ⚡\n\n"
            f"<b>Trader:</b> Zia\n"
            f"<b>Asset:</b> {sig.asset}\n"
            f"<b>Action:</b> {emoji_dir}\n"
            f"<b>Confidence Score:</b> {sig.evidence_score}/100 ({sig.strength.value})\n"
            f"<b>Recommended Expiry:</b> {sig.recommended_expiry // 60} min ({sig.recommended_expiry}s)\n"
            f"<b>Entry Price:</b> {sig.entry_price:.5f}\n"
            f"<b>Market Regime:</b> {sig.regime.trend.value} ({sig.regime.session})\n"
            f"<b>Economic Viability:</b> {'✅ Viable' if sig.is_economically_viable else '⚠️ Marginal'}\n\n"
            f"<b>Supporting Evidence:</b>\n{evidence_lines}\n\n"
            f"<i>Time: {sig.timestamp.strftime('%H:%M:%S UTC')}</i>"
        )

        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": msg,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            }
            resp = requests.post(url, json=payload, timeout=5)
            return resp.status_code == 200
        except Exception:
            return False
