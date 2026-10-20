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
- Self-test the turn-start script after any edits to `tools/`:
  ```bash
  bash tools/test-turn-start.sh
  ```

## 4. Performance Investigation Summary (1,000+ Game Libraries)
1. **Per-Game JSON-RPC `FuzzySearch` IPC Round-Trips (`src/plugin/__main__.py`):**
   - `await plugin.launcher.api.fuzzy_search(query, game.name)` in `python_v2` mode sends a synchronous-sequenced JSON-RPC request over `stdout` to Flow Launcher and awaits the reply on `stdin` for *every single game* in the loop ($O(N)$ sequential cross-process pipe round-trips per keystroke).
2. **Live Library Server TCP Timeout Penalty on Every Keystroke (`src/plugin/library_server.py`):**
   - `fetch_games()` calls `urllib.request.urlopen("http://localhost:38217/...", timeout=0.3)` on every query without negative caching/backoff. On Windows, `localhost` resolves to both IPv6 (`::1`) and IPv4 (`127.0.0.1`), and connecting to an unlistened loopback port hits the timeout per address family (300ms–600ms blocking penalty per keystroke when the optional server isn't running).
3. **No In-Memory Library Cache Across Queries in a Long-Lived `python_v2` Process (`src/plugin/playnite.py`, `src/plugin/__main__.py`):**
   - Even though `python_v2` keeps the Python process alive across queries and `cached_copy()` checks `(st_mtime_ns, st_size)` on disk, `lib.games()` re-reads the entire `games.db` and `sources.db` into memory and BSON-decodes all 1,000+ full documents (including HTML descriptions, GUID arrays, links) on every single keystroke (~90–150ms CPU per keystroke).
4. **3x Synchronous Disk `stat()` (`Path.is_file()`) Per Game in `build_result` (`src/plugin/results.py`, `src/plugin/playnite.py`):**
   - `build_result()` calls `media_path()` 3 times per game (`cover_image`, `icon` in `Result`, and `icon` again inside `context_payload()`). Each `media_path()` calls `path.is_file()`. For 1,000+ games, that is 3,000+ synchronous NTFS `stat` calls per keystroke.
5. **Unbounded Result Construction & Serialization (`src/plugin/__main__.py`):**
   - Empty or broad queries construct, stat, and JSON-serialize `Result` objects for all 1,000+ games (>1 MB of JSON per query) instead of capping/paginating to top matches, and `hide_uninstalled` filtering happens *after* constructing all `Game` objects.
