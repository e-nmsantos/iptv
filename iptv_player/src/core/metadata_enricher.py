"""TMDB / IMDb movie and series metadata enricher for VOD content."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# TMDB image/endpoint constants. The API key is NOT stored here: see
# MetadataEnricher.__init__, which takes it as an argument or reads
# IPTV_TMDB_API_KEY.
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/"
TMDB_SEARCH_MOVIE_URL = "https://api.themoviedb.org/3/search/movie"
TMDB_SEARCH_TV_URL = "https://api.themoviedb.org/3/search/tv"


class MovieMetadata:
    """Enriched metadata for a Movie or TV Series."""

    def __init__(
        self,
        title: str,
        year: Optional[int] = None,
        overview: str = "",
        rating: float = 0.0,
        poster_url: str = "",
        backdrop_url: str = "",
        genres: str = "",
    ):
        self.title = title
        self.year = year
        self.overview = overview
        self.rating = rating
        self.poster_url = poster_url
        self.backdrop_url = backdrop_url
        self.genres = genres

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "year": self.year,
            "overview": self.overview,
            "rating": self.rating,
            "poster_url": self.poster_url,
            "backdrop_url": self.backdrop_url,
            "genres": self.genres,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MovieMetadata":
        return cls(
            title=data.get("title", ""),
            year=data.get("year"),
            overview=data.get("overview", ""),
            rating=float(data.get("rating", 0.0)),
            poster_url=data.get("poster_url", ""),
            backdrop_url=data.get("backdrop_url", ""),
            genres=data.get("genres", ""),
        )


class MetadataEnricher:
    """Asynchronously fetches and caches TMDB metadata for movies and series.

    The TMDB API key must be supplied by the caller or through the
    ``IPTV_TMDB_API_KEY`` environment variable. It is deliberately no longer
    defaulted in code: the previous hardcoded value shipped a shared secret in
    every build (and should be rotated on the TMDB account).
    """

    def __init__(self, api_key: Optional[str] = None, cache_dir: Optional[Path] = None):
        self._api_key = api_key or os.environ.get("IPTV_TMDB_API_KEY", "")
        if cache_dir is None:
            try:
                from config.settings import Settings
                cache_dir = Settings().config_dir
            except Exception:
                cache_dir = Path.home() / ".config" / "iptv-player"
        self._cache_file = cache_dir / "tmdb_metadata_cache.json"
        self._cache: dict[str, dict] = self._load_cache()

    def _load_cache(self) -> dict[str, dict]:
        if self._cache_file.exists():
            try:
                with open(self._cache_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self):
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @staticmethod
    def extract_title_and_year(raw_title: str) -> tuple[str, Optional[int]]:
        """Extract clean title and optional year (e.g. 'Inception (2010)' or 'Inception 2010' -> ('Inception', 2010))."""
        clean = re.sub(r"\[.*?\]", "", raw_title).strip()
        match = re.search(r"\((\d{4})\)", clean)
        year = None
        if match:
            year = int(match.group(1))
            clean = clean[:match.start()] + clean[match.end():]
        else:
            match_bare = re.search(r"\b(19\d{2}|20\d{2})\b", clean)
            if match_bare:
                year = int(match_bare.group(1))
                clean = clean[:match_bare.start()] + clean[match_bare.end():]

        clean = re.sub(r"\b(1080p|720p|4k|fhd|hd|uhd|hevc|h265|bluray|web-dl)\b", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip(" -._|[]()")
        return clean or raw_title, year

    def fetch_movie_metadata(self, title: str) -> Optional[MovieMetadata]:
        """Fetch movie metadata from TMDB with local cache fallback."""
        clean_title, year = self.extract_title_and_year(title)
        cache_key = f"movie:{clean_title.casefold()}:{year or ''}"

        if cache_key in self._cache:
            return MovieMetadata.from_dict(self._cache[cache_key])

        if not self._api_key:
            return None

        try:
            params = {
                "api_key": self._api_key,
                "query": clean_title,
                "language": "pt-PT",
                "include_adult": "false",
            }
            if year:
                params["year"] = year

            resp = requests.get(TMDB_SEARCH_MOVIE_URL, params=params, timeout=5)
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                if results:
                    first = results[0]
                    poster_path = first.get("poster_path")
                    backdrop_path = first.get("backdrop_path")
                    meta = MovieMetadata(
                        title=first.get("title") or clean_title,
                        year=int(first.get("release_date", "")[:4]) if first.get("release_date") else year,
                        overview=first.get("overview", ""),
                        rating=round(float(first.get("vote_average", 0.0)), 1),
                        poster_url=f"{TMDB_IMAGE_BASE}w500{poster_path}" if poster_path else "",
                        backdrop_url=f"{TMDB_IMAGE_BASE}w1280{backdrop_path}" if backdrop_path else "",
                    )
                    self._cache[cache_key] = meta.to_dict()
                    self._save_cache()
                    return meta
        except Exception as e:
            logger.debug("TMDB lookup failed: %s", e)

        return None
