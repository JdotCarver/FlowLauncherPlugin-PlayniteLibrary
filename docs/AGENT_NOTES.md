<!-- docs/AGENT_NOTES.md -->
# Agent Notes — FlowLauncherPlugin-PlayniteLibrary

## 1. Session & Branch Invariants
- **Session Branch:** `arena/38b2e790-flowlauncherplugin-playnitelib`
- **Base Commit:** `bcc2ebf242b74d50c2123693080312abf6771937`
- **Turn-Start Routine:** Always run `bash tools/arena-turn-start.sh` at the start of every turn (and after user-facing pauses like `ask_user` / `present_file`) to sync with remote and guard against harness snapshot restores.
- **Coding Conventions:**
  - Every file starts with its relative file path commented at the top (VSCode convention, e.g., `# src/plugin/playnite.py`).
  - Self-documenting, human-readable code over clever brevity.
  - Follow SOLID principles and YAGNI.
  - "Measure twice, Cut once": Always align on design/shape before implementing changes.

## 2. Harness Recovery & Turn-Start Repair
If `bash tools/arena-turn-start.sh` reports a problem:
- **Shallow clone on re-clone:** Run `git fetch --unshallow origin` so ancestry checks (`git merge-base --is-ancestor`) have the full commit graph.
- **Diverged history after a mid-turn re-clone:** If a harness snapshot restore reset `HEAD` to `BASE_COMMIT` and a new commit was created on top of `BASE_COMMIT` while `origin/arena/38b2e790-flowlauncherplugin-playnitelib` holds earlier session commits:
  ```bash
  git diff --stat origin/arena/38b2e790-flowlauncherplugin-playnitelib
  git reset --soft origin/arena/38b2e790-flowlauncherplugin-playnitelib
  git commit -C HEAD@{1}
  ```
  Never force-push over the user's commits.
- **Key load-bearing files (`KEY_FILES`):**
  - `data/plugin.json`
  - `src/run.py`
  - `src/plugin/__main__.py`
  - `src/plugin/playnite.py`
  - `src/plugin/matcher.py`
  - `src/plugin/library_source.py`
  - `src/plugin/library_server.py`
  - `src/plugin/results.py`
  - `src/plugin/settings.py`
  - `docs/AGENT_NOTES.md`

## 3. Sandbox Environment & Test Runner
- `.venv` is excluded from Arena snapshots, so if the sandbox resets or reclones, recreate it with:
  ```bash
  python3 -m venv .venv && .venv/bin/pip install -q pytest pytest-asyncio -r requirements.txt
  ```
- Run tests via:
  ```bash
  .venv/bin/pytest -v
  ```
- Run the end-to-end performance benchmark against `ressources/games.db` (1,725 games):
  ```bash
  .venv/bin/python tools/benchmark_library.py
  ```
- Self-test the turn-start script after any edits to `tools/`:
  ```bash
  bash tools/test-turn-start.sh
  ```

## 4. Implemented Optimizations & Benchmark Results (`ressources/games.db`, 1,725 Games)
1. **Opt-in Live Library Server (`use_library_server`, default `False`) + `127.0.0.1` loopback (`src/plugin/library_source.py`, `src/plugin/library_server.py`):**
   - Eliminates the 300–600ms per-keystroke TCP connection timeout on Windows when the companion server extension is not used.
   - Standardizes settings checkboxes in `data/SettingsTemplate.yaml` to opt-in "Show / Use" toggles (`show_hidden`: default `true`, `show_uninstalled`: default `true`, `use_library_server`: default `false`), while preserving backwards compatibility with `hide_uninstalled`.
2. **In-Memory Library & Media Path Caching (`src/plugin/playnite.py`, `src/plugin/__main__.py`):**
   - Reuses `PlayniteLibrary` across queries in the persistent `python_v2` process and caches parsed/pre-sorted `Game` lists keyed by the `(games.db, sources.db)` snapshot paths (`st_mtime_ns` + `st_size`).
   - Caches `media_path` lookups (`@lru_cache(maxsize=4096)`) and deduplicates `media_path(files_dir, game.icon)` in `build_result` / `context_payload`.
3. **In-Process Fuzzy Matching, Ranking & Result Capping (`src/plugin/matcher.py`):**
   - Replaces 1,725 sequential JSON-RPC `FuzzySearch` stdio round-trips per keystroke with in-process matching using C-level ordered-character pre-filtering (`str.find`) + unwrapped `pyflowlauncher.string_matcher` (avoiding 128-entry `lru_cache` thrashing).
   - Precomputes `name_lower` and `sort_key` on `Game` instances at load time.
   - Caps empty queries at top 10 (`EMPTY_QUERY_LIMIT = 10`, ordered by `last_activity` desc -> `playtime` desc -> `name` asc) and search queries at top 25 (`SEARCH_QUERY_LIMIT = 25`, ordered by `score` desc) *before* invoking `build_result` and disk `stat()` checks.
4. **Measured Results (`tools/benchmark_library.py` on 1,725-game `ressources/games.db`):**
   - **8-keystroke typing (all 1,725 games):** `1,510.52 ms` (188.81 ms/keystroke) -> **`24.98 ms` (3.12 ms/keystroke, 60.5x faster)**
   - **8-keystroke typing (15 installed games):** `1,362.60 ms` (170.32 ms/keystroke) -> **`1.18 ms` (0.15 ms/keystroke, 1,158.9x faster)**
   - **25 diverse queries (all 1,725 games):** `4,700.41 ms` (188.02 ms/query) -> **`31.82 ms` (1.27 ms/query, 147.7x faster)**
   - *(Note: On Windows, where baseline also suffered 300–600ms TCP loopback timeout + stdio IPC round-trips per keystroke, real-world speedup is **>150x–3,000x**).*
