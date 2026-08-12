"""EPG (Electronic Program Guide) data models."""

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Optional


@dataclass
class EPGProgram:
    """Represents a single TV program in the EPG."""

    channel_id: str
    title: str
    start: datetime
    stop: datetime
    description: str = ""
    category: str = ""
    episode: str = ""
    icon: str = ""
    rating: str = ""

    @property
    def duration_minutes(self) -> int:
        """Get program duration in minutes."""
        delta = self.stop - self.start
        return int(delta.total_seconds() / 60)

    @property
    def is_live(self) -> bool:
        """Check if the program is currently live."""
        now = datetime.now(self.start.tzinfo)
        return self.start <= now <= self.stop

    @property
    def progress(self) -> float:
        """Get playback progress as a 0-1 float."""
        if self.is_live:
            total = (self.stop - self.start).total_seconds()
            elapsed = (datetime.now(self.start.tzinfo) - self.start).total_seconds()
            return min(elapsed / total, 1.0) if total > 0 else 0.0
        return 0.0


@dataclass
class EPGSource:
    """Represents an EPG data source (XMLTV file/URL)."""

    name: str
    url: str = ""
    file_path: str = ""
    channels: dict = field(default_factory=dict)  # channel_id -> list of programs
    last_updated: Optional[datetime] = None

    def add_program(self, program: EPGProgram):
        """Add a program to the EPG source."""
        if program.channel_id not in self.channels:
            self.channels[program.channel_id] = []
        self.channels[program.channel_id].append(program)

    def get_programs(self, channel_id: str) -> list:
        """Get all programs for a specific channel."""
        return self.channels.get(channel_id, [])

    def get_current_program(self, channel_id: str) -> Optional[EPGProgram]:
        """Get the currently playing program for a channel."""
        programs = self.channels.get(channel_id, [])
        for prog in programs:
            if prog.is_live:
                return prog
        return None

    def get_next_program(self, channel_id: str) -> Optional[EPGProgram]:
        """Get the next program after the current one."""
        programs = self.channels.get(channel_id, [])
        tzinfo = programs[0].start.tzinfo if programs else None
        now = datetime.now(tzinfo)
        next_progs = [p for p in programs if p.start > now]
        return min(next_progs, key=lambda p: p.start) if next_progs else None

    @staticmethod
    def parse_xmltv(xml_content: str) -> "EPGSource":
        """Parse XMLTV formatted EPG data."""
        return EPGSource.parse_xmltv_stream(BytesIO(xml_content.encode("utf-8")))

    @staticmethod
    def parse_xmltv_stream(stream) -> "EPGSource":
        """Incrementally parse XMLTV bytes without retaining the XML tree."""
        source = EPGSource(name="XMLTV Import")
        root = None

        for event, element in ET.iterparse(stream, events=("start", "end")):
            if root is None:
                root = element
            if event != "end" or element.tag.rsplit("}", 1)[-1] != "programme":
                continue

            channel_id = element.get("channel", "")
            start_str = element.get("start", "")
            stop_str = element.get("stop", "")

            children = {child.tag.rsplit("}", 1)[-1]: child for child in element}
            title_elem = children.get("title")
            desc_elem = children.get("desc")
            cat_elem = children.get("category")

            try:
                start = _parse_xmltv_time(start_str)
                stop = _parse_xmltv_time(stop_str)
            except ValueError:
                element.clear()
                if root is not None:
                    root.clear()
                continue

            program = EPGProgram(
                channel_id=channel_id,
                title=(title_elem.text or "Unknown") if title_elem is not None else "Unknown",
                start=start,
                stop=stop,
                description=(desc_elem.text or "") if desc_elem is not None else "",
                category=(cat_elem.text or "") if cat_elem is not None else "",
            )
            source.add_program(program)
            element.clear()
            if root is not None:
                root.clear()

        return source


def _parse_xmltv_time(time_str: str) -> datetime:
    """Parse XMLTV time format (YYYYMMDDHHMMSS [+-]HHMM)."""
    value = time_str.strip()
    for fmt in ("%Y%m%d%H%M%S %z", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid XMLTV timestamp: {time_str!r}")
