"""Utility functions for the IPTV Player."""

import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse


def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS."""
    if seconds < 0:
        return "00:00"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def clean_url(url: str) -> str:
    """Clean and normalize a URL."""
    url = url.strip().strip('"').strip("'")
    url = url.replace("\\", "")
    return url


def parse_epg_time(time_str: str) -> Optional[datetime]:
    """Parse various EPG time formats to datetime."""
    formats = [
        "%Y%m%d%H%M%S %z",
        "%Y%m%d%H%M%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%d/%m/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(time_str.strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def sanitize_filename(filename: str) -> str:
    """Remove invalid characters from filenames."""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, "", filename)
    sanitized = sanitized.strip(". ")
    return sanitized[:200]  # Limit length


def is_valid_url(url: str) -> bool:
    """Check if a string is a valid URL."""
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except Exception:
        return False


def human_readable_size(size_bytes: int) -> str:
    """Convert bytes to human-readable size."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"
