"""
Structured Logging Module
=========================
Outputs clean timestamped logs with execution context for audits and debugging.
"""

import logging
import sys
from pathlib import Path

from app.config import PROJECT_ROOT


def setup_structured_logger(name: str = "TradingPlatform", log_file: str = "platform.log") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        # Console Formatter
        console_handler = logging.StreamHandler(sys.stdout)
        console_fmt = logging.Formatter(
            "[%(asctime)s UTC] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_fmt)
        logger.addHandler(console_handler)

        # File Formatter
        logs_dir = PROJECT_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(logs_dir / log_file, encoding="utf-8")
        file_fmt = logging.Formatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%SZ"
        )
        file_handler.setFormatter(file_fmt)
        logger.addHandler(file_handler)

    return logger
