"""Alerts and notification dispatchers package."""
from .telegram_bot import TelegramAlertDispatcher
from .desktop import DesktopAlertDispatcher

__all__ = ["TelegramAlertDispatcher", "DesktopAlertDispatcher"]
