# tools/benchmark_library.py
"""Benchmark comparing the baseline v3.3.1 query pipeline against the optimized pipeline
using the real 1,725-game Playnite database in ``ressources/games.db``.
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src" / "plugin"))

from pyflowlauncher.result import send_results  # noqa: E402
from pyflowlauncher.string_matcher import string_matcher  # noqa: E402

from library_source import games as library_source_games  # noqa: E402
from matcher import match_and_rank_games  # noqa: E402
from playnite import Game, LiteDatabase, PlayniteLibrary, game_subtitle  # noqa: E402
from results import build_result  # noqa: E402

REAL_DB = REPO_ROOT / "ressources" / "games.db"

TYPING_QUERIES = ["", "r", "ra", "rav", "rave", "raven", "ravens", "ravenswatch"]
DIVERSE_QUERIES = [
    "", "s", "sk", "sky", "ravenswatch", "witcher", "doom", "diablo",
    "final fantasy", "baldur", "rdr2", "gta", "star wars", "resident evil",
    "hollow knight", "cyberpunk", "elden", "dark souls", "zelda", "persona",
    "monster hunter", "hades", "celeste", "dead", "xyz_no_match",
]


def uncached_media_path(files_dir: Path, relative: str | None) -> Path | None:
    if not relative:
        return None
    path = Path(files_dir, *relative.split("\\"))
    return path if path.is_file() else None


def baseline_read_games(data_dir: Path, cache_dir: Path, include_hidden: bool) -> list[Game]:
    """Reproduce v3.3.1 PlayniteLibrary.games() without in-memory caching."""
    lib = PlayniteLibrary(data_dir, cache_dir=cache_dir)
    sources = lib.source_names()
    with LiteDatabase(lib.cached_copy(lib.games_db)) as db:
        games = [Game.from_doc(doc, sources) for doc in db["Game"]]
    return [game for game in games if include_hidden or not game.hidden]


async def run_benchmarks() -> None:
    if not REAL_DB.is_file():
        print(f"Missing benchmark database at {REAL_DB}", file=sys.stderr)
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        data_dir = tmp_path / "Playnite"
        library_dir = data_dir / "library"
        files_dir = library_dir / "files"
        library_dir.mkdir(parents=True)
        files_dir.mkdir(parents=True)
        shutil.copy(REAL_DB, library_dir / "games.db")

        seed_lib = PlayniteLibrary(data_dir, cache_dir=tmp_path / "seed_cache")
        all_games = seed_lib.games(include_hidden=True)
        for game in all_games[:300]:
            if game.icon and not game.icon.startswith("http"):
                icon_path = files_dir / Path(*game.icon.split("\\"))
                icon_path.parent.mkdir(parents=True, exist_ok=True)
                if not icon_path.exists():
                    icon_path.write_bytes(b"icon")
            if game.cover_image and not game.cover_image.startswith("http"):
                cover_path = files_dir / Path(*game.cover_image.split("\\"))
                cover_path.parent.mkdir(parents=True, exist_ok=True)
                if not cover_path.exists():
                    cover_path.write_bytes(b"cover")

        baseline_cache = tmp_path / "baseline_cache"

        async def baseline_query(query_text: str, *, show_uninstalled: bool, include_hidden: bool):
            games = baseline_read_games(data_dir, baseline_cache, include_hidden=include_hidden)
            if not show_uninstalled:
                games = [game for game in games if game.is_installed]
            results = []
            for game in games:
                score = 0
                if query_text:
                    match = string_matcher(query_text, game.name)
                    if match.score < match.score_cutoff:
                        continue
                    score = int(match.score)
                # v3.3.1 performed 3 uncached Path.is_file() checks per matched game
                _ = uncached_media_path(files_dir, game.cover_image)
                _ = uncached_media_path(files_dir, game.icon)
                _ = uncached_media_path(files_dir, game.icon)
                _ = game_subtitle(game)
                results.append(build_result(game, files_dir, score))
            return send_results(results)

        opt_lib = PlayniteLibrary(data_dir, cache_dir=tmp_path / "opt_cache")

        async def optimized_query(query_text: str, *, show_uninstalled: bool, include_hidden: bool):
            games = library_source_games(
                server_port=38217,
                include_hidden=include_hidden,
                fallback=opt_lib,
                use_server=False,
            )
            if not show_uninstalled:
                games = [game for game in games if game.is_installed]
            results = [
                build_result(game, opt_lib.files_dir, score)
                for game, score in match_and_rank_games(games, query_text)
            ]
            return send_results(results)

        # Measure Baseline
        t0 = time.perf_counter()
        base_cold_res = await baseline_query("", show_uninstalled=True, include_hidden=True)
        base_cold_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for q in TYPING_QUERIES:
            await baseline_query(q, show_uninstalled=True, include_hidden=True)
        base_typing_all_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for q in TYPING_QUERIES:
            await baseline_query(q, show_uninstalled=False, include_hidden=False)
        base_typing_inst_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for q in DIVERSE_QUERIES:
            await baseline_query(q, show_uninstalled=True, include_hidden=True)
        base_diverse_ms = (time.perf_counter() - t0) * 1000

        # Measure Optimized
        t0 = time.perf_counter()
        opt_cold_res = await optimized_query("", show_uninstalled=True, include_hidden=True)
        opt_cold_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for q in TYPING_QUERIES:
            await optimized_query(q, show_uninstalled=True, include_hidden=True)
        opt_typing_all_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for q in TYPING_QUERIES:
            await optimized_query(q, show_uninstalled=False, include_hidden=False)
        opt_typing_inst_ms = (time.perf_counter() - t0) * 1000

        t0 = time.perf_counter()
        for q in DIVERSE_QUERIES:
            await optimized_query(q, show_uninstalled=True, include_hidden=True)
        opt_diverse_ms = (time.perf_counter() - t0) * 1000

        print(f"Library: {REAL_DB.name} ({len(all_games)} total games, {sum(g.is_installed for g in all_games)} installed)")
        print("-" * 88)
        print(f"{'Scenario':42} | {'Baseline (v3.3.1)':>17} | {'Optimized':>13} | {'Speedup':>8}")
        print("-" * 88)
        print(
            f"{'Cold query (empty, first load)':42} | "
            f"{base_cold_ms:14.2f} ms | {opt_cold_ms:10.2f} ms | {base_cold_ms / opt_cold_ms:7.1f}x"
        )
        print(
            f"{'8-keystroke typing (all 1,725 games)':42} | "
            f"{base_typing_all_ms:14.2f} ms | {opt_typing_all_ms:10.2f} ms | {base_typing_all_ms / opt_typing_all_ms:7.1f}x"
        )
        print(
            f"{'  -> per keystroke (all 1,725 games)':42} | "
            f"{base_typing_all_ms / len(TYPING_QUERIES):14.2f} ms | "
            f"{opt_typing_all_ms / len(TYPING_QUERIES):10.2f} ms | "
            f"{base_typing_all_ms / opt_typing_all_ms:7.1f}x"
        )
        print(
            f"{'8-keystroke typing (15 installed games)':42} | "
            f"{base_typing_inst_ms:14.2f} ms | {opt_typing_inst_ms:10.2f} ms | {base_typing_inst_ms / opt_typing_inst_ms:7.1f}x"
        )
        print(
            f"{'  -> per keystroke (15 installed games)':42} | "
            f"{base_typing_inst_ms / len(TYPING_QUERIES):14.2f} ms | "
            f"{opt_typing_inst_ms / len(TYPING_QUERIES):10.2f} ms | "
            f"{base_typing_inst_ms / opt_typing_inst_ms:7.1f}x"
        )
        print(
            f"{'25 diverse queries (all 1,725 games)':42} | "
            f"{base_diverse_ms:14.2f} ms | {opt_diverse_ms:10.2f} ms | {base_diverse_ms / opt_diverse_ms:7.1f}x"
        )
        print(
            f"{'  -> per query (all 1,725 games)':42} | "
            f"{base_diverse_ms / len(DIVERSE_QUERIES):14.2f} ms | "
            f"{opt_diverse_ms / len(DIVERSE_QUERIES):10.2f} ms | "
            f"{base_diverse_ms / opt_diverse_ms:7.1f}x"
        )
        print(
            f"{'Empty query result count':42} | "
            f"{len(base_cold_res['Result']):17d} | {len(opt_cold_res['Result']):13d} |"
        )
        print("-" * 88)


if __name__ == "__main__":
    asyncio.run(run_benchmarks())
