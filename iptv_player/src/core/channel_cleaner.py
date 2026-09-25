"""Channel name sanitizer and Logical Channel Numbering (LCN) manager."""

import re
from typing import Optional

from .channel import Channel


class ChannelCleaner:
    """Cleans noisy IPTV channel names and assigns clean logical channel numbers."""

    # Regex patterns for noisy prefixes and quality tags
    _PREFIX_PATTERNS = [
        r"^(?:PT|PT-PT|PORTUGAL|ES|UK|US|FR|DE|IT)\s*[:|\-]\s*",
        r"^\[(?:PT|PT-PT|PORTUGAL|ES|UK|US|FR|DE|IT)\]\s*",
        r"^\d+\s*[-:.)]\s*",
    ]

    _QUALITY_TAGS = [
        r"\[(?:FHD|HD|4K|UHD|SD|HEVC|H265|H264|RAW|BACKUP|AUTO|LOCAL|DIRECT)\]",
        r"\((?:FHD|HD|4K|UHD|SD|HEVC|H265|H264|RAW|BACKUP|AUTO|LOCAL|DIRECT|1080P|720P|50FPS|60FPS)\)",
        r"\b(?:FHD|UHD|4K|1080P|720P|50FPS|60FPS|H\.?265|H\.?264|HEVC|RAW|HD|SD)\b",
        r"[-:]\s*(?:BACKUP|RESERVA|AUTO|DIRECT)\b",
    ]

    @classmethod
    def clean_name(cls, raw_name: str) -> str:
        """Strip country prefixes, resolution tags and noise to produce a clean display name."""
        if not raw_name:
            return ""

        cleaned = raw_name.strip()

        # Remove country/region prefixes
        for pattern in cls._PREFIX_PATTERNS:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE).strip()

        # Remove quality/codec tags
        for tag in cls._QUALITY_TAGS:
            cleaned = re.sub(tag, "", cleaned, flags=re.IGNORECASE).strip()

        # Collapse excess whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Clean trailing separators like '-' or '|'
        cleaned = re.sub(r"[\s|\-:]+$", "", cleaned).strip()

        return cleaned or raw_name

    clean_channel_name = clean_name

    @classmethod
    def assign_lcn(
        cls,
        channels: list[Channel],
        preferred_order: Optional[list[str]] = None,
    ) -> list[tuple[int, Channel, str]]:
        """
        Assign logical channel numbers (1, 2, 3...) to a list of channels.
        Returns a list of (lcn_number, channel, clean_display_name).
        """
        results: list[tuple[int, Channel, str]] = []
        clean_map: dict[str, list[Channel]] = {}

        for ch in channels:
            clean = cls.clean_name(ch.name)
            clean_map.setdefault(clean.casefold(), []).append(ch)

        current_number = 1
        for channel in channels:
            clean = cls.clean_name(channel.name)
            results.append((current_number, channel, clean))
            current_number += 1

        return results

    @classmethod
    def find_alternate_streams(
        cls,
        target_channel: Channel,
        all_channels: list[Channel],
    ) -> list[Channel]:
        """Find backup/alternative streams for the same television channel."""
        target_clean = cls.clean_name(target_channel.name).casefold()
        if not target_clean:
            return []

        candidates = []
        for ch in all_channels:
            if ch.url == target_channel.url:
                continue
            if getattr(ch, "stream_type", "live") != getattr(target_channel, "stream_type", "live"):
                continue

            clean = cls.clean_name(ch.name).casefold()
            # Exact clean name match or tvg_id match
            if clean == target_clean or (ch.tvg_id and ch.tvg_id == target_channel.tvg_id):
                candidates.append(ch)

        return candidates
