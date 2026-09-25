"""Catalogue content-type vocabulary shared across the application.

The live/vod/series split used to be re-implemented with literal strings and
literal ``{0: "live", 1: "vod", 2: "series"}`` maps in half a dozen modules, and
the ``"movie"`` alias of ``vod`` was easy to forget in one of them. Keeping a
single definition here removes that class of drift.
"""

LIVE = "live"
VOD = "vod"
SERIES = "series"

#: The three catalogue buckets, in UI tab order.
CONTENT_TYPES: tuple[str, ...] = (LIVE, VOD, SERIES)

#: Content-tab index -> catalogue content type.
TAB_CONTENT_TYPES: dict[int, str] = {0: LIVE, 1: VOD, 2: SERIES}

#: Provider ``stream_type`` values accepted by each catalogue content type.
STREAM_TYPES_BY_CONTENT: dict[str, tuple[str, ...]] = {
    LIVE: (LIVE,),
    VOD: (VOD, "movie"),
    SERIES: (SERIES,),
}

#: Every ``stream_type`` a provider may report for a playable item.
ALL_STREAM_TYPES: tuple[str, ...] = (LIVE, VOD, "movie", SERIES)


def content_type_for_tab(index: int, default: str = LIVE) -> str:
    """Return the catalogue content type shown by a content-tab index."""
    return TAB_CONTENT_TYPES.get(index, default)


def content_type_for_stream(stream_type: str) -> str:
    """Normalise a channel ``stream_type`` onto a catalogue content type.

    Returns ``""`` for values that belong to no bucket, so callers can skip
    the item instead of silently filing it under "live".
    """
    if stream_type == LIVE:
        return LIVE
    if stream_type in STREAM_TYPES_BY_CONTENT[VOD]:
        return VOD
    if stream_type == SERIES:
        return SERIES
    return ""
