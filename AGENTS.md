# AGENTS.md

## Cursor Cloud specific instructions

Agentic Board is a Python (FastAPI + `uv`) backend plus a React/Vite frontend in `ui/`.
See `README.md` and `CLAUDE.md` for architecture, CLI flags, API endpoints, and model routing.

### Services

| Service | How to run | Port | Notes |
|---|---|---|---|
| Backend API + built UI | `./start.sh` | 8000 | Builds `ui/` then runs `uvicorn server.api:app --reload`. Serves the React build and the API from one origin. |
| Backend API only | `uv run uvicorn server.api:app --reload --port 8000` | 8000 | Frontend uses relative URLs, so this alone serves everything once `ui/dist` exists. |
| Frontend dev (hot reload) | `cd ui && npm run dev` | 5173 | Vite proxies API routes to `127.0.0.1:8000`, so the backend must also be running. |
| CLI | `uv run python -m server.cli --list-members` (etc.) | — | Headless deliberation; same key requirements as the backend. |

- `uv` installs to `~/.local/bin` (already on `PATH` after the update script). `start.sh` auto-discovers `.venv/bin/uvicorn`.
- The API is **localhost-only** by default; it rejects non-local requests unless `AGENTIC_BOARD_ALLOW_REMOTE=1`. When testing from the VM browser, use `http://127.0.0.1:8000`.
- Persistence is fully local (SQLite ledger at `data/harness_ledger.db` + session JSON under `data/`). No Postgres/Redis or other external datastore is needed. `data/` is gitignored.

### Provider API keys (required for real deliberation only)

The server **boots, serves the UI, `/members`, and the CLI roster without any keys**, but any actual
deliberation (`POST /deliberate`, CLI questions) calls external LLM providers and fails with
`0/N members responded` when keys are missing. Set keys in a `.env` file (copy `.env.example`).
Default models span 5 providers (`DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `GEMINI_API_KEY`,
`ZAI_API_KEY`, `DASHSCOPE_API_KEY`).

To drive a full deliberation from a **single** key (e.g. Gemini free tier), override every model role
and allow same-provider verification:

```bash
CHAIRMAN_MODEL=gemini/gemini-2.5-flash
COUNCIL_MODELS=gemini/gemini-2.5-flash
CLASSIFIER_MODEL=gemini/gemini-2.5-flash
VERIFICATION_MODEL=gemini/gemini-2.5-flash
AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1
```

### Tests / lint / build

- Backend tests: `uv run pytest` (config uses `-m 'not live'`, so `live` provider-hitting tests are skipped by default).
- Frontend type-check + build: `cd ui && npm run check` (`tsc --noEmit && vite build`).
- Known pre-existing failures unrelated to setup: `tests/test_replay_contract.py::CliFlagExistsTest::test_cli_accepts_replay_flag` hardcodes an absolute `.venv` path from the original author's machine, and two `tests/test_harness_integration_contract.py` cases require a real `ZAI_API_KEY`.
