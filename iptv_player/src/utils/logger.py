"""Logging configuration for the IPTV Player."""

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:username|password|token|play_token|auth|mac)=)[^&\s]+"
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


def setup_logger(name: str = "iptv_player") -> logging.Logger:
    """
    Set up and configure the application logger.
    
    Creates both console and file handlers with appropriate formatting.
    Log files are stored in the app config directory.
    
    Args:
        name: Logger name
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Console handler (INFO and above)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_SensitiveDataFilter())
    logger.addHandler(console_handler)

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
        logger.addHandler(file_handler)
    except Exception as e:
        logger.warning(f"Could not create file handler: {e}")

    # Modules log through logging.getLogger(__name__) ("src.core...", "config..."),
    # which are not children of this logger; route them to the same handlers.
    if name == "iptv_player":
        for package in ("src", "config"):
            package_logger = logging.getLogger(package)
            if not package_logger.handlers:
                package_logger.setLevel(logging.DEBUG)
                package_logger.propagate = False
                for handler in logger.handlers:
                    package_logger.addHandler(handler)

    return logger


def get_logger(name: str = "iptv_player") -> logging.Logger:
    """Get an existing logger or create a new one."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        return setup_logger(name)
    return logger
