# tests/test_performance.py
import shutil
import time
from pathlib import Path

import pytest

from library_source import games as library_source_games
from matcher import EMPTY_QUERY_LIMIT, SEARCH_QUERY_LIMIT, match_and_rank_games
from playnite import PlayniteLibrary
from results import build_result

REAL_DB = Path(__file__).parent.parent / "ressources" / "games.db"
TYPING_SEQUENCE = ["", "r", "ra", "rav", "rave", "raven", "ravens", "ravenswatch"]


@pytest.mark.skipif(not REAL_DB.is_file(), reason="no real Playnite games.db in ressources/")
def test_typing_sequence_performance_across_full_library(tmp_path):
    library_dir = tmp_path / "Playnite" / "library"
    files_dir = library_dir / "files"
    library_dir.mkdir(parents=True)
    files_dir.mkdir(parents=True)
    shutil.copy(REAL_DB, library_dir / "games.db")

    lib = PlayniteLibrary(tmp_path / "Playnite", cache_dir=tmp_path / "cache")

    # Warm the initial database read (simulating persistent python_v2 process after first query)
    initial_games = lib.games(include_hidden=True)
    assert len(initial_games) >= 1000

    start_time = time.perf_counter()
    for query_text in TYPING_SEQUENCE:
        candidate_games = library_source_games(
            server_port=38217,
            include_hidden=True,
            fallback=lib,
            use_server=False,
        )
        ranked = match_and_rank_games(candidate_games, query_text)
        results = [build_result(game, lib.files_dir, score) for game, score in ranked]
        if not query_text:
            assert len(results) == EMPTY_QUERY_LIMIT
        else:
            assert len(results) <= SEARCH_QUERY_LIMIT
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # Baseline took >1,500ms on Linux and >4,500ms on Windows for 8 keystrokes;
    # optimized implementation completes in ~20-30ms (<100ms budget with generous CI headroom).
    assert elapsed_ms < 100.0, f"8-keystroke typing sequence took {elapsed_ms:.2f}ms (expected < 100ms)"


@pytest.mark.skipif(not REAL_DB.is_file(), reason="no real Playnite games.db in ressources/")
def test_typing_sequence_performance_installed_only(tmp_path):
    library_dir = tmp_path / "Playnite" / "library"
    files_dir = library_dir / "files"
    library_dir.mkdir(parents=True)
    files_dir.mkdir(parents=True)
    shutil.copy(REAL_DB, library_dir / "games.db")

    lib = PlayniteLibrary(tmp_path / "Playnite", cache_dir=tmp_path / "cache")
    _ = lib.games(include_hidden=False)

    start_time = time.perf_counter()
    for query_text in TYPING_SEQUENCE:
        candidate_games = library_source_games(
            server_port=38217,
            include_hidden=False,
            fallback=lib,
            use_server=False,
        )
        installed_games = [game for game in candidate_games if game.is_installed]
        ranked = match_and_rank_games(installed_games, query_text)
        results = [build_result(game, lib.files_dir, score) for game, score in ranked]
        assert len(results) <= EMPTY_QUERY_LIMIT if not query_text else len(results) <= SEARCH_QUERY_LIMIT
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert elapsed_ms < 25.0, f"Installed-only 8-keystroke sequence took {elapsed_ms:.2f}ms (expected < 25ms)"
