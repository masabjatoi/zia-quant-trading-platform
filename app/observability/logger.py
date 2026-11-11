"""
Structured Logging Module
=========================
Outputs clean UTC-timestamped logs with secret redaction for audits and debugging.
"""

import logging
import re
import sys
import time
from pathlib import Path
from typing import Pattern, Tuple, List

from app.config import PROJECT_ROOT


class SecretRedactingFilter(logging.Filter):
    """Redacts tokens, passwords, HMAC secrets, and URL credentials from log records."""

    _PATTERNS: List[Tuple[Pattern[str], str]] = [
        # Telegram bot token in URL path
        (re.compile(r"(https?://api\.telegram\.org/)?bot\d+:[A-Za-z0-9_-]{15,}", re.IGNORECASE), r"\1bot[REDACTED]"),
        # URLs with embedded credentials scheme://user:pass@host
        (re.compile(r"([a-zA-Z][a-zA-Z0-9+.-]*://[^:/@\s]+:)([^@\s]+)(@)"), r"\1[REDACTED]\3"),
        # Authorization headers / Bearer tokens
        (re.compile(r"(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE), r"\1[REDACTED]"),
        # Key=value or JSON-like secret fields
        (
            re.compile(
                r"""(["']?(?:password|passwd|secret|token|bot_token|api_key|apikey|hmac|signature|x-bridge-token|x-bridge-signature|database_url|render_postgres_url)["']?\s*[:=]\s*["']?)([^\s,"'&}]+)""",
                re.IGNORECASE,
            ),
            r"\1[REDACTED]",
        ),
    ]

    @classmethod
    def redact(cls, text: str) -> str:
        if not isinstance(text, str):
            text = str(text)
        for pattern, repl in cls._PATTERNS:
            text = pattern.sub(repl, text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            rendered = str(record.msg)
        redacted = self.redact(rendered)
        if redacted != rendered:
            record.msg = redacted
            record.args = ()
        if record.exc_text:
            record.exc_text = self.redact(record.exc_text)
        return True


class UTCFormatter(logging.Formatter):
    converter = time.gmtime


def redact_secret_text(text: str) -> str:
    """Public helper for sanitizing exception strings before storing/returning diagnostics."""
    return SecretRedactingFilter.redact(text)


def setup_structured_logger(name: str = "TradingPlatform", log_file: str = "platform.log") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if not logger.handlers:
        redactor = SecretRedactingFilter()

        # Console Formatter
        console_handler = logging.StreamHandler(sys.stdout)
        console_fmt = UTCFormatter(
            "[%(asctime)s UTC] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        console_handler.setFormatter(console_fmt)
        console_handler.addFilter(redactor)
        logger.addHandler(console_handler)

        # File Formatter with size-based rotation to protect Render disk quotas
        from logging.handlers import RotatingFileHandler

        logs_dir = PROJECT_ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            logs_dir / log_file,
            maxBytes=2 * 1024 * 1024,  # 2 MB per file
            backupCount=3,             # Keep at most 3 backups (6MB max total)
            encoding="utf-8",
        )
        file_fmt = UTCFormatter(
            '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%SZ",
        )
        file_handler.setFormatter(file_fmt)
        file_handler.addFilter(redactor)
        logger.addHandler(file_handler)

    return logger
