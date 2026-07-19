# Agentic Board — Agent Notes

Project overview, architecture, run/CLI/API reference: see `CLAUDE.md` and `README.md`.

## Cursor Cloud specific instructions

Dependencies (Python via `uv`, UI via `npm`) are installed by the startup update
script, so you normally don't need to reinstall them. The notes below are the
non-obvious, durable gotchas for running/testing this repo.

### Services & how to run them
- **Web app (API + built UI, single origin):** `./start.sh` → `http://127.0.0.1:8000`.
  `start.sh` rebuilds the UI (`ui/dist`) on every start, then runs uvicorn with
  `--reload` scoped to `server/`. This is the simplest way to exercise the full
  product. Override host/port with `HOST` / `PORT` env vars.
- **API only:** `uv run uvicorn server.api:app --reload --port 8000`.
- **CLI (same deliberation engine, no UI/server):** `uv run python -m server.cli ...`
  (e.g. `--list-members`, `--full-board "..."`). See `CLAUDE.md` for all flags.
- **UI hot-reload dev (optional, two processes):** backend on 8000 +
  `npm --prefix ui run dev` (Vite on 5173). Caveat: the Vite dev proxy in
  `ui/vite.config.ts` does **not** proxy `/initiatives`, so initiative features
  break in pure Vite-dev mode. Use `./start.sh` (single origin :8000) to test
  initiatives end-to-end.

### LLM keys are required for real deliberation
- No provider keys are set by default. The core board deliberation (Stage 1–4)
  and the live "secretary brief" make **real** provider calls and will fail
  without keys (`DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `GEMINI_API_KEY`,
  `ZAI_API_KEY`, `DASHSCOPE_API_KEY` — see `.env.example` / `CLAUDE.md`).
- Flows that work **without** any keys: listing members, initiatives
  (create/activate/close, persisted to SQLite), SOTB memory read/write, and
  session listing. Use these for smoke-testing the environment.

### Testing / lint / build
- **Tests:** `uv run pytest`. Live provider tests are deselected by default via
  `addopts = -m 'not live'` in `pyproject.toml`; `pytest -m live` needs real keys.
- **UI typecheck + build (closest thing to a lint):** `npm --prefix ui run check`
  (`tsc --noEmit && vite build`). There is **no** Python linter configured
  (no ruff/flake8/black/mypy).
- **Known pre-existing failures with no keys / fresh checkout** (not caused by
  setup, do not "fix" by editing code):
  - `tests/test_replay_contract.py::CliFlagExistsTest::test_cli_accepts_replay_flag`
    hardcodes a former developer's absolute venv path (`/home/apeng/...`).
  - `tests/test_harness_integration_contract.py::LedgerWiringAsyncContractTest`
    (2 tests) invoke the secretary-brief LLM and require `ZAI_API_KEY`.

### Runtime data
- All state is local: `data/sessions/` (JSON), SQLite ledgers/stores under
  `data/`, and `server/memory/sotb.md`. Created on first use; no DB service needed.
