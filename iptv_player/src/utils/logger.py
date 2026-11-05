"""Logging configuration for the IPTV Player."""

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:username|password|token|auth|mac)=)[^&\s]+"
)
_XTREAM_PATH_SECRET = re.compile(
    r"(?i)(/(?:live|movie|series)/)[^/\s]+/[^/\s]+/"
)
_MAC_ADDRESS = re.compile(r"(?i)\b[0-9a-f]{2}(?::[0-9a-f]{2}){5}\b")


def redact_sensitive(message: str) -> str:
    """Remove common IPTV credentials from diagnostic messages."""
    value = str(message)
    value = _QUERY_SECRET.sub(r"\1***", value)
    value = _XTREAM_PATH_SECRET.sub(r"\1***/***/", value)
    return _MAC_ADDRESS.sub("**:**:**:**:**:**", value)


def log_file_path() -> Path:
    """Return the on-disk log file path used by the file handler."""
    if os.name == "nt":
        log_dir = (
            Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
            / "iptv-player"
            / "logs"
        )
    else:
        log_dir = Path.home() / ".config" / "iptv-player" / "logs"
    return log_dir / "iptv_player.log"


class _SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_sensitive(record.getMessage())
        record.args = ()
        return True


_CONFIGURED_ATTR = "_iptv_player_configured"

# Third-party libraries that would otherwise flood the DEBUG file handler.
_NOISY_LOGGERS = (
    "urllib3",
    "requests",
    "charset_normalizer",
    "pychromecast",
    "zeroconf",
    "asyncio",
)


def setup_logger(name: str = "iptv_player") -> logging.Logger:
    """
    Set up and configure application-wide logging.

    Handlers live on the root logger so that every module logger
    (``logging.getLogger(__name__)``) writes to the same console and file
    output with the credential-redaction filter applied. Configuration runs
    only once per process.

    Args:
        name: Logger name

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    root = logging.getLogger()
    if not getattr(root, _CONFIGURED_ATTR, False):
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler (INFO and above)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        console_handler.addFilter(_SensitiveDataFilter())
        root.addHandler(console_handler)

        # File handler (DEBUG and above)
        try:
            log_file = log_file_path()
            log_file.parent.mkdir(parents=True, exist_ok=True)

            file_handler = RotatingFileHandler(
                str(log_file),
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_SensitiveDataFilter())
            root.addHandler(file_handler)
        except Exception as e:
            root.warning("Could not create file handler: %s", e)

        root.setLevel(logging.DEBUG)
        for noisy in _NOISY_LOGGERS:
            logging.getLogger(noisy).setLevel(logging.WARNING)
        setattr(root, _CONFIGURED_ATTR, True)

    return logger


def get_logger(name: str = "iptv_player") -> logging.Logger:
    """Get an existing logger or create a new one."""
    if not getattr(logging.getLogger(), _CONFIGURED_ATTR, False):
        return setup_logger(name)
    return logging.getLogger(name)
