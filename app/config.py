"""
Configuration Manager
=====================
Loads YAML configuration, handles asset definitions, session definitions,
and validates application settings.
"""

import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "configs"
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_DIR = PROJECT_ROOT / "database"

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class AssetSpec:
    symbol: str
    name: str
    ticker: str
    category: str
    payout: float
    pip_size: float
    active_sessions: List[str]

    @property
    def breakeven_winrate(self) -> float:
        """Required win rate to break even at current payout."""
        return 1.0 / (1.0 + self.payout)


# Active Trading Session UTC intervals
TRADING_SESSIONS_UTC = {
    "sydney": (21, 6),     # 21:00 to 06:00 UTC
    "tokyo": (0, 9),       # 00:00 to 09:00 UTC
    "london": (7, 16),     # 07:00 to 16:00 UTC
    "new_york": (12, 21),  # 12:00 to 21:00 UTC
}


class ConfigManager:
    """Singleton-style configuration loader and manager."""
    _instance: Optional["ConfigManager"] = None

    def __init__(self, config_file: Optional[str] = None):
        if config_file is None:
            config_file = str(CONFIG_DIR / "default.yaml")
        self.config_path = Path(config_file)
        self.raw_config: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.config_path.exists():
            with open(self.config_path, "r", encoding="utf-8") as f:
                self.raw_config = yaml.safe_load(f) or {}
        else:
            self.raw_config = {}

    def get(self, key_path: str, default: Any = None) -> Any:
        """Fetch nested key using dot notation e.g. 'signals.min_evidence_score'."""
        keys = key_path.split(".")
        val = self.raw_config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    @property
    def assets(self) -> Dict[str, AssetSpec]:
        assets_data = self.get("assets", {})
        result = {}
        for sym, d in assets_data.items():
            result[sym] = AssetSpec(
                symbol=sym,
                name=d.get("name", sym),
                ticker=d.get("ticker", sym),
                category=d.get("category", "forex"),
                payout=float(d.get("payout", 0.85)),
                pip_size=float(d.get("pip_size", 0.0001)),
                active_sessions=d.get("active_sessions", ["all"]),
            )
        return result

    @property
    def primary_timeframe(self) -> str:
        return self.get("timeframes.primary", "1m")

    @property
    def confirmation_timeframes(self) -> List[str]:
        return self.get("timeframes.confirmation", ["5m", "15m"])

    @property
    def supported_timeframes(self) -> List[str]:
        return self.get("timeframes.supported", ["1m", "5m", "15m"])

    def get_timeframe_profile(self, timeframe: str = "1m") -> Dict[str, Any]:
        profiles = self.get("timeframes.profiles", {})
        if timeframe in profiles:
            return profiles[timeframe]
        
        # Fallback profile defaults
        fallback_map = {
            "1m": {
                "candle_interval": "1m",
                "expiry_seconds": 60,
                "htf_confirmations": ["5m", "15m"],
                "cooldown_seconds": 60,
                "min_evidence_score": 55,
                "min_atr_percentile": 5.0
            },
            "5m": {
                "candle_interval": "5m",
                "expiry_seconds": 300,
                "htf_confirmations": ["15m", "1h"],
                "cooldown_seconds": 120,
                "min_evidence_score": 55,
                "min_atr_percentile": 5.0
            },
            "15m": {
                "candle_interval": "15m",
                "expiry_seconds": 900,
                "htf_confirmations": ["1h", "4h"],
                "cooldown_seconds": 300,
                "min_evidence_score": 55,
                "min_atr_percentile": 5.0
            }
        }
        return fallback_map.get(timeframe, fallback_map["1m"])

    @property
    def expiries(self) -> List[int]:
        return self.get("expiries.durations", [60, 300, 900])

    @property
    def default_expiry(self) -> int:
        return self.get("expiries.default", 60)

    @property
    def db_url(self) -> str:
        # Check environment variables (Render PostgreSQL or external database)
        env_db_url = os.environ.get("DATABASE_URL") or os.environ.get("RENDER_POSTGRES_URL")
        if env_db_url:
            # Fix legacy postgres:// dialect prefix for SQLAlchemy 1.4/2.0
            if env_db_url.startswith("postgres://"):
                env_db_url = env_db_url.replace("postgres://", "postgresql://", 1)
            return env_db_url

        db_path = DATABASE_DIR / "platform.db"
        return f"sqlite:///{db_path}"

    @property
    def random_seed(self) -> int:
        return int(self.get("system.random_seed", 42))


# Global config instance
config = ConfigManager()
