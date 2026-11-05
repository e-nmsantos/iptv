"""TMDB metadata enrichment: title parsing, cache and failure handling."""

import json

import pytest

from src.core import metadata_enricher
from src.core.metadata_enricher import MetadataEnricher, MovieMetadata


@pytest.fixture
def enricher(tmp_path):
    return MetadataEnricher(api_key="test-key", cache_dir=tmp_path)


class TestTitleExtraction:
    @pytest.mark.parametrize(
        ("raw", "title", "year"),
        [
            ("Inception (2010)", "Inception", 2010),
            ("Inception 2010", "Inception", 2010),
            ("Dune 2021 1080p BluRay", "Dune", 2021),
            ("Oppenheimer [4K] (2023)", "Oppenheimer", 2023),
            ("Sem ano", "Sem ano", None),
            ("", "", None),
        ],
    )
    def test_extracts_title_and_year(self, raw, title, year):
        parsed_title, parsed_year = MetadataEnricher.extract_title_and_year(raw)

        assert parsed_title == title
        assert parsed_year == year


class TestMovieMetadataModel:
    def test_round_trip(self):
        original = MovieMetadata(
            title="Filme",
            year=2020,
            overview="Sinopse",
            rating=7.5,
            poster_url="http://p",
            backdrop_url="http://b",
            genres="Drama",
        )

        restored = MovieMetadata.from_dict(original.to_dict())

        assert restored.__dict__ == original.__dict__

    def test_missing_fields_use_defaults(self):
        restored = MovieMetadata.from_dict({})

        assert restored.title == ""
        assert restored.year is None
        assert restored.rating == 0.0


class TestLookup:
    def test_without_api_key_nothing_is_fetched(self, tmp_path, monkeypatch):
        called = []
        monkeypatch.setattr(metadata_enricher.requests, "get", lambda *a, **k: called.append(1))
        enricher = MetadataEnricher(api_key="", cache_dir=tmp_path)

        assert enricher.fetch_movie_metadata("Filme (2020)") is None
        assert called == []

    def test_successful_lookup_is_cached(self, enricher, tmp_path, monkeypatch):
        class _Response:
            status_code = 200

            @staticmethod
            def json():
                return {
                    "results": [
                        {
                            "title": "Filme",
                            "release_date": "2020-05-01",
                            "overview": "Sinopse",
                            "vote_average": 7.456,
                            "poster_path": "/p.jpg",
                            "backdrop_path": "/b.jpg",
                        }
                    ]
                }

        calls = []

        def fake_get(url, params=None, timeout=None):
            calls.append(url)
            return _Response()

        monkeypatch.setattr(metadata_enricher.requests, "get", fake_get)

        metadata = enricher.fetch_movie_metadata("Filme (2020)")

        assert metadata.title == "Filme"
        assert metadata.year == 2020
        assert metadata.rating == 7.5
        assert metadata.poster_url.endswith("/w500/p.jpg")
        assert metadata.backdrop_url.endswith("/w1280/b.jpg")
        assert len(calls) == 1

        # Cache hit: no second request.
        again = enricher.fetch_movie_metadata("Filme (2020)")
        assert again.title == "Filme"
        assert len(calls) == 1

        cache_file = tmp_path / "tmdb_metadata_cache.json"
        assert json.loads(cache_file.read_text(encoding="utf-8"))

    def test_empty_results_return_none(self, enricher, monkeypatch):
        class _Response:
            status_code = 200

            @staticmethod
            def json():
                return {"results": []}

        monkeypatch.setattr(metadata_enricher.requests, "get", lambda *a, **k: _Response())

        assert enricher.fetch_movie_metadata("Desconhecido") is None

    def test_http_error_returns_none(self, enricher, monkeypatch):
        class _Response:
            status_code = 500

            @staticmethod
            def json():
                return {}

        monkeypatch.setattr(metadata_enricher.requests, "get", lambda *a, **k: _Response())

        assert enricher.fetch_movie_metadata("Filme") is None

    def test_network_failure_returns_none(self, enricher, monkeypatch):
        def boom(*args, **kwargs):
            raise ConnectionError("sem rede")

        monkeypatch.setattr(metadata_enricher.requests, "get", boom)

        assert enricher.fetch_movie_metadata("Filme") is None

    def test_cache_file_is_reloaded_from_disk(self, tmp_path):
        cache_file = tmp_path / "tmdb_metadata_cache.json"
        cache_file.write_text(
            json.dumps({"movie:filme:": {"title": "Filme em cache", "year": 1999}}),
            encoding="utf-8",
        )

        enricher = MetadataEnricher(api_key="k", cache_dir=tmp_path)

        metadata = enricher.fetch_movie_metadata("Filme")
        assert metadata.title == "Filme em cache"
        assert metadata.year == 1999
