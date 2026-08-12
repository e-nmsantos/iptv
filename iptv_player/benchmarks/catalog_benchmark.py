"""Reproducible local benchmark for large encrypted IPTV catalogues."""

import argparse
import gc
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path

from src.core.channel import Channel
from src.core.database import DatabaseManager
from src.core.playlist import Playlist
from src.core.secrets import SecretStore


def make_channels(size: int) -> list[Channel]:
    """Generate deterministic synthetic data; no provider details are required."""
    return [
        Channel(
            name=f"Canal {index:06d}",
            url=f"https://example.invalid/live/{index}",
            group=f"Categoria {index % 100:03d}",
            tvg_id=f"channel-{index}",
            xtream_id=str(index),
            source="benchmark",
            stream_type="live",
        )
        for index in range(size)
    ]


def measure(callable_, repeats: int = 1):
    durations = []
    result = None
    for _ in range(repeats):
        gc.collect()
        started = time.perf_counter()
        result = callable_()
        durations.append(time.perf_counter() - started)
    return statistics.median(durations), result


def run_case(size: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="iptv-benchmark-") as directory:
        db = DatabaseManager(
            Path(directory) / "catalog.db",
            SecretStore.for_tests(),
        )
        channels = make_channels(size)
        playlist = Playlist(name="Benchmark", source_type="m3u", channels=channels)

        tracemalloc.start()
        insert_seconds, playlist_id = measure(lambda: db.save_playlist(playlist))
        _, peak_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        differential_seconds, _ = measure(
            lambda: db.replace_catalog(playlist_id, "live", channels)
        )

        page_seconds, page = measure(
            lambda: db.get_channel_page(playlist_id, "live", page=0),
            repeats=5,
        )
        search_seconds, matches = measure(
            lambda: db.search_channels(playlist_id, "Canal 0001"),
            repeats=3,
        )
        count_seconds, count = measure(
            lambda: db.count_channels(playlist_id, "live"), repeats=5
        )
        return {
            "size": size,
            "insert_seconds": insert_seconds,
            "differential_seconds": differential_seconds,
            "first_page_seconds": page_seconds,
            "search_seconds": search_seconds,
            "count_seconds": count_seconds,
            "page_items": len(page),
            "search_items": len(matches),
            "count": count,
            "peak_mib": peak_bytes / 1024 / 1024,
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[10_000, 50_000, 100_000],
        help="Synthetic catalogue sizes to measure",
    )
    parser.add_argument(
        "--enforce-budget",
        action="store_true",
        help="Fail on the documented 100k performance/memory budgets",
    )
    args = parser.parse_args()
    print(
        "items | insert(s) | unchanged refresh(s) | first page(s) | "
        "search(s) | count(s) | peak MiB"
    )
    print("-" * 96)
    failures = []
    for size in args.sizes:
        result = run_case(size)
        print(
            f"{result['size']:>6} | {result['insert_seconds']:>9.3f} | "
            f"{result['differential_seconds']:>20.3f} | "
            f"{result['first_page_seconds']:>13.4f} | "
            f"{result['search_seconds']:>9.4f} | "
            f"{result['count_seconds']:>8.4f} | {result['peak_mib']:>8.1f}"
        )
        if args.enforce_budget and size >= 100_000:
            budgets = {
                "insert_seconds": 240.0,
                "differential_seconds": 90.0,
                "first_page_seconds": 0.5,
                "search_seconds": 0.5,
                "count_seconds": 0.2,
                "peak_mib": 256.0,
            }
            failures.extend(
                f"{metric}={result[metric]:.3f} > {limit:.3f}"
                for metric, limit in budgets.items()
                if result[metric] > limit
            )
    if failures:
        raise SystemExit("Performance budget exceeded: " + ", ".join(failures))


if __name__ == "__main__":
    main()
