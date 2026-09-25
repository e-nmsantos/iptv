import base64
import gzip
import io
import logging
import re
import ssl
import urllib.parse
import xmlrpc.client
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

VLSub_USER_AGENT = "VLSub 0.10.2"
VLSub_XMLRPC_URL = "https://api.opensubtitles.org/xml-rpc"
OPENSUBTITLES_USER_AGENT = "VLSub 0.10.2"
OPENSUBTITLES_REST_BASE = "https://rest.opensubtitles.org/search"


class SubtitleResult:
    """Represents a downloaded or available subtitle track."""

    def __init__(
        self,
        subtitle_id: str,
        language: str,
        release_name: str,
        download_url: str = "",
        rating: float = 0.0,
        downloads_count: int = 0,
        source: str = "vlsub",
    ):
        self.subtitle_id = subtitle_id
        self.language = language
        self.release_name = release_name
        self.download_url = download_url
        self.rating = rating
        self.downloads_count = downloads_count
        self.source = source

    def __repr__(self):
        return f"<SubtitleResult [{self.language}] {self.release_name}>"


class SubtitlesFinder:
    """Finds and downloads subtitles using VLC's native VLSub XML-RPC and Stremio CDN."""

    _LANG_MAP = {
        "pt": "por",
        "pt-pt": "por",
        "por": "por",
        "pob": "pob",
        "pt-br": "pob",
        "br": "pob",
        "en": "eng",
        "eng": "eng",
        "es": "spa",
        "spa": "spa",
        "fr": "fre",
        "fre": "fre",
        "de": "ger",
        "ger": "ger",
        "it": "ita",
        "ita": "ita",
    }

    def __init__(self, cache_dir: Optional[Path] = None):
        if cache_dir is None:
            cache_dir = Path.home() / ".config" / "iptv-player" / "subtitles"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._vlsub_token: Optional[str] = None

    def _get_vlsub_proxy(self):
        ctx = ssl._create_unverified_context()
        return xmlrpc.client.ServerProxy(VLSub_XMLRPC_URL, context=ctx)

    def _get_vlsub_token(self) -> Optional[str]:
        if self._vlsub_token:
            return self._vlsub_token
        try:
            proxy = self._get_vlsub_proxy()
            res = proxy.LogIn("", "", "pt", VLSub_USER_AGENT)
            if isinstance(res, dict) and res.get("status", "").startswith("200"):
                self._vlsub_token = res.get("token")
        except Exception as e:
            logger.debug("VLSub login error: %s", e)
        return self._vlsub_token

    def search_subtitles(
        self,
        query: str = "",
        languages: str = "pt,pob,en",
        year: Optional[int] = None,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        imdb_id: Optional[str] = None,
    ) -> list[SubtitleResult]:
        """Search for subtitles online matching title, season/episode, or IMDb ID."""
        raw_langs = [lang.strip().lower() for lang in languages.split(",") if lang.strip()]
        target_sublangs = {self._LANG_MAP.get(lang, lang) for lang in raw_langs}
        if not target_sublangs:
            target_sublangs = {"por", "pob", "eng"}

        results: list[SubtitleResult] = []
        seen_keys = set()

        # 1. Primary Engine: Official VLC VLSub XML-RPC protocol
        vlsub_results = self._search_vlsub_engine(
            query=query,
            target_sublangs=target_sublangs,
            year=year,
            season_number=season_number,
            episode_number=episode_number,
            imdb_id=imdb_id,
        )
        for r in vlsub_results:
            key = (r.language, r.release_name.lower())
            if key not in seen_keys:
                seen_keys.add(key)
                results.append(r)

        # 2. Secondary Engine: Stremio OpenSubtitles CDN
        if len(results) < 10:
            cdn_results = self._search_stremio_engine(
                query=query,
                target_sublangs=target_sublangs,
                year=year,
                season_number=season_number,
                episode_number=episode_number,
                imdb_id=imdb_id,
            )
            for r in cdn_results:
                key = (r.language, r.release_name.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    results.append(r)

        # Smart sorting: PT-PT and PT-BR first, then downloads and ratings
        def sort_priority(r: SubtitleResult):
            lang_pri = 0 if r.language in ("PT-PT", "PT") else 1 if r.language in ("PT-BR", "POB") else 2 if r.language == "EN" else 3
            return (lang_pri, -r.downloads_count, -r.rating)

        results.sort(key=sort_priority)
        return results

    def _search_vlsub_engine(
        self,
        query: str,
        target_sublangs: set,
        year: Optional[int] = None,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        imdb_id: Optional[str] = None,
    ) -> list[SubtitleResult]:
        """Search subtitles via VLC VLSub XML-RPC API."""
        results: list[SubtitleResult] = []
        token = self._get_vlsub_token()
        if not token:
            return []

        try:
            proxy = self._get_vlsub_proxy()
            lang_param = ",".join(target_sublangs)
            search_param: dict[str, object] = {"sublanguageid": lang_param}

            if imdb_id:
                clean_imdb = str(imdb_id).strip().lower().replace("tt", "")
                if clean_imdb.isdigit():
                    search_param["imdbid"] = clean_imdb
            elif query:
                clean_query = query.strip()
                if year:
                    clean_query = f"{clean_query} {year}"
                search_param["query"] = clean_query
                if season_number is not None:
                    search_param["season"] = str(season_number)
                if episode_number is not None:
                    search_param["episode"] = str(episode_number)

            resp = proxy.SearchSubtitles(token, [search_param])
            if isinstance(resp, dict) and isinstance(resp.get("data"), list):
                for item in resp["data"]:
                    sub_lang = str(item.get("SubLanguageID", "")).lower()
                    if target_sublangs and sub_lang not in target_sublangs and "all" not in target_sublangs:
                        continue
                    file_id = str(item.get("IDSubtitleFile", item.get("IDSubtitle", "")))
                    if not file_id:
                        continue
                    rel_name = (
                        item.get("MovieReleaseName")
                        or item.get("SubFileName")
                        or item.get("MovieName")
                        or query
                        or "Legenda"
                    ).strip()
                    display_lang = "PT-PT" if sub_lang == "por" else "PT-BR" if sub_lang == "pob" else sub_lang.upper()
                    rating = float(item.get("SubRating", 0.0) or 0.0)
                    downloads = int(item.get("SubDownloadsCnt", 0) or 0)
                    results.append(
                        SubtitleResult(
                            subtitle_id=file_id,
                            language=display_lang,
                            release_name=rel_name,
                            download_url=item.get("SubDownloadLink", ""),
                            rating=rating,
                            downloads_count=downloads,
                            source="vlsub",
                        )
                    )
        except Exception as e:
            logger.debug("VLSub search error: %s", e)
            self._vlsub_token = None

        return results

    def _search_stremio_engine(
        self,
        query: str,
        target_sublangs: set,
        year: Optional[int] = None,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        imdb_id: Optional[str] = None,
    ) -> list[SubtitleResult]:
        """Primary fast subtitle resolver via Stremio OpenSubtitles CDN."""
        import concurrent.futures
        results: list[SubtitleResult] = []
        is_series = season_number is not None and episode_number is not None
        candidate_ids = []

        if imdb_id:
            clean = str(imdb_id).strip().lower()
            if not clean.startswith("tt") and clean.isdigit():
                clean = f"tt{int(clean):07d}"
            candidate_ids.append(clean)
        elif query:
            # Query Cinemeta metadata catalog for matching IMDb IDs
            try:
                cat_type = "series" if is_series else "movie"
                q_clean = query.strip()
                meta_url = f"https://v3-cinemeta.strem.io/catalog/{cat_type}/top/search={urllib.parse.quote(q_clean)}.json"
                resp = requests.get(meta_url, timeout=3.5)
                if resp.status_code == 200:
                    metas = resp.json().get("metas", [])
                    # Pick top matching candidates (up to 4)
                    for m in metas[:4]:
                        mid = m.get("id")
                        if mid and mid not in candidate_ids:
                            candidate_ids.append(mid)
            except Exception as e:
                logger.debug("Cinemeta metadata lookup error: %s", e)

        if not candidate_ids:
            return []

        def fetch_for_id(cid: str) -> list[SubtitleResult]:
            sub_res = []
            try:
                if is_series:
                    sub_url = f"https://opensubtitles-v3.strem.io/subtitles/series/{cid}:{season_number}:{episode_number}.json"
                else:
                    sub_url = f"https://opensubtitles-v3.strem.io/subtitles/movie/{cid}.json"

                resp = requests.get(sub_url, timeout=3.5)
                if resp.status_code == 200:
                    subs = resp.json().get("subtitles", [])
                    for item in subs:
                        item_lang = str(item.get("lang", "")).lower()
                        if target_sublangs and item_lang not in target_sublangs and "all" not in target_sublangs:
                            continue
                        dl_url = item.get("url", "")
                        if not dl_url:
                            continue
                        rel_name = (
                            item.get("movieReleaseName")
                            or item.get("subtitleFileName")
                            or query
                            or "Legenda"
                        ).strip()
                        display_lang = "PT-PT" if item_lang == "por" else "PT-BR" if item_lang == "pob" else item_lang.upper()
                        sub_res.append(
                            SubtitleResult(
                                subtitle_id=str(item.get("id", "")),
                                language=display_lang,
                                release_name=rel_name,
                                download_url=dl_url,
                                rating=10.0,
                                downloads_count=50,
                            )
                        )
            except Exception as ex:
                logger.debug("Error fetching subs for %s: %s", cid, ex)
            return sub_res

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(candidate_ids)) as executor:
            for sub_list in executor.map(fetch_for_id, candidate_ids):
                results.extend(sub_list)

        return results

    def _search_rest_engine(
        self,
        query: str,
        target_sublangs: set,
        year: Optional[int] = None,
        season_number: Optional[int] = None,
        episode_number: Optional[int] = None,
        imdb_id: Optional[str] = None,
    ) -> list[SubtitleResult]:
        """Secondary fallback subtitle resolver via OpenSubtitles REST API."""
        import concurrent.futures
        results: list[SubtitleResult] = []
        headers = {
            "User-Agent": OPENSUBTITLES_USER_AGENT,
            "Accept": "application/json",
        }

        def fetch_sublang(sublang: str) -> list[SubtitleResult]:
            sub_res = []
            try:
                path_parts = []
                if imdb_id:
                    clean_imdb = str(imdb_id).strip().lower().replace("tt", "")
                    if clean_imdb.isdigit():
                        path_parts.append(f"imdbid-{clean_imdb}")
                elif query:
                    clean_query = query.strip().lower()
                    if season_number is not None and episode_number is not None:
                        clean_query = f"{clean_query} s{season_number:02d}e{episode_number:02d}"
                    elif year:
                        clean_query = f"{clean_query} {year}"
                    encoded_q = urllib.parse.quote(clean_query)
                    path_parts.append(f"query-{encoded_q}")

                path_parts.append(f"sublanguageid-{sublang}")

                url = f"{OPENSUBTITLES_REST_BASE}/" + "/".join(path_parts)
                resp = requests.get(url, headers=headers, timeout=3.5)
                if resp.status_code == 200:
                    data = resp.json()
                    if isinstance(data, list):
                        for item in data:
                            dl_link = item.get("SubDownloadLink") or item.get("ZipDownloadLink") or ""
                            rel_name = (
                                item.get("MovieReleaseName")
                                or item.get("SubFileName")
                                or item.get("MovieName")
                                or query
                                or "Legenda"
                            ).strip()
                            sub_lang_id = (item.get("SubLanguageID") or sublang).lower()
                            display_lang = "PT-PT" if sub_lang_id == "por" else "PT-BR" if sub_lang_id == "pob" else sub_lang_id.upper()
                            rating = float(item.get("SubRating", 0.0) or 0.0)
                            downloads = int(item.get("SubDownloadsCnt", 0) or 0)
                            sub_res.append(
                                SubtitleResult(
                                    subtitle_id=str(item.get("IDSubtitleFile", item.get("IDSubtitle", ""))),
                                    language=display_lang,
                                    release_name=rel_name,
                                    download_url=dl_link,
                                    rating=rating,
                                    downloads_count=downloads,
                                )
                            )
            except Exception as e:
                logger.debug("OpenSubtitles REST search exception for %s: %s", sublang, e)
            return sub_res

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(target_sublangs))) as executor:
            for sub_list in executor.map(fetch_sublang, list(target_sublangs)):
                results.extend(sub_list)

        return results

    def download_subtitle_file(self, result: SubtitleResult) -> Optional[Path]:
        """Download subtitle track (via VLSub XML-RPC or direct CDN), decompress, and save as UTF-8 .srt file."""
        try:
            clean_name = re.sub(r'[\W_]+', '_', result.release_name or "subtitles")
            filename = f"{clean_name}_{result.language}.srt"
            text = ""

            # 1. Direct XML-RPC download from VLSub engine
            if result.source == "vlsub" and result.subtitle_id.isdigit():
                token = self._get_vlsub_token()
                if token:
                    try:
                        proxy = self._get_vlsub_proxy()
                        dl_resp = proxy.DownloadSubtitles(token, [int(result.subtitle_id)])
                        if isinstance(dl_resp, dict) and dl_resp.get("data"):
                            raw_b64 = dl_resp["data"][0].get("data", "")
                            if raw_b64:
                                decompressed = gzip.decompress(base64.b64decode(raw_b64))
                                for enc in ("utf-8", "cp1252", "latin-1", "iso-8859-1"):
                                    try:
                                        text = decompressed.decode(enc)
                                        break
                                    except Exception:
                                        continue
                    except Exception as ex:
                        logger.debug("VLSub DownloadSubtitles RPC error: %s", ex)

            # 2. HTTP CDN stream download
            if not text and result.download_url and result.download_url.startswith("http"):
                try:
                    headers = {"User-Agent": VLSub_USER_AGENT}
                    resp = requests.get(result.download_url, headers=headers, timeout=6)
                    if resp.status_code == 200:
                        content_bytes = resp.content
                        try:
                            decompressed = gzip.GzipFile(fileobj=io.BytesIO(content_bytes)).read()
                        except Exception:
                            decompressed = content_bytes

                        for enc in ("utf-8", "cp1252", "latin-1", "iso-8859-1"):
                            try:
                                text = decompressed.decode(enc)
                                break
                            except Exception:
                                continue
                except Exception as ex:
                    logger.debug("HTTP download error: %s", ex)

            if text:
                return self.save_subtitle_file(text, filename)

            logger.debug("No subtitle content retrieved for %s", result.release_name)
            return None
        except Exception as e:
            logger.warning("Failed to download subtitle: %s", e)
            return None

    def save_subtitle_file(self, content_text: str, filename: str) -> Path:
        """Save subtitle content as UTF-8 encoded .srt in cache directory."""
        if not filename.endswith(".srt"):
            filename += ".srt"
        target_path = self.cache_dir / filename
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content_text)
        return target_path

