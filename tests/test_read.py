# tests/test_read.py
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from playnite import LiteDatabase, PlayniteLibrary

FIXTURE_DB = Path(__file__).parent / "fixtures" / "guids.db"
REPO_REAL_DB = Path(__file__).parent.parent / "ressources" / "games.db"
HOME_REAL_DB = Path.home() / "projects" / "games.db"
REAL_DB = REPO_REAL_DB if REPO_REAL_DB.is_file() else HOME_REAL_DB


def make_library(tmp_path, db_file, sources_file=None):
    library = tmp_path / "Playnite" / "library"
    library.mkdir(parents=True)
    shutil.copy(db_file, library / "games.db")
    if sources_file:
        shutil.copy(sources_file, library / "sources.db")
    return PlayniteLibrary(tmp_path / "Playnite", cache_dir=tmp_path / "cache")


def test_source_names_empty_without_sources_db(tmp_path):
    lib = make_library(tmp_path, FIXTURE_DB)
    assert lib.source_names() == {}


def test_source_names_ignores_corrupt_sources_db(tmp_path):
    library = tmp_path / "Playnite" / "library"
    library.mkdir(parents=True)
    shutil.copy(FIXTURE_DB, library / "games.db")
    (library / "sources.db").write_bytes(b"not a litedb file at all")
    lib = PlayniteLibrary(tmp_path / "Playnite", cache_dir=tmp_path / "cache")
    assert lib.source_names() == {}


@pytest.mark.skipif(not REAL_DB.is_file(), reason="no real Playnite games.db available")
def test_reads_real_playnite_library(tmp_path):
    lib = make_library(tmp_path, REAL_DB)
    games = lib.games(include_hidden=True)
    assert len(games) > 0
    assert all(game.id and game.name for game in games)
    visible = lib.games(include_hidden=False)
    assert len(visible) <= len(games)


@pytest.mark.skipif(not REAL_DB.is_file(), reason="no real Playnite games.db available")
def test_games_uses_in_memory_cache_on_repeated_calls(tmp_path):
    lib = make_library(tmp_path, REAL_DB)
    first_read = lib.games(include_hidden=True)

    with patch("playnite.LiteDatabase", wraps=LiteDatabase) as spy_db:
        second_read = lib.games(include_hidden=True)
        visible_read = lib.games(include_hidden=False)
        installed_read = lib.games(include_hidden=False, include_uninstalled=False)
        assert spy_db.call_count == 0

    assert second_read == first_read
    assert len(visible_read) <= len(first_read)
    assert all(game.is_installed for game in installed_read)
