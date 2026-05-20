# Agentic Board

A council of world-expert AI agents that deliberate as a company board of directors.

## Project Structure

```text
/home/apeng/projects/solo_company_agentic_board/
├── server/                  # Backend service and board runtime
│   ├── api/                 # FastAPI app and HTTP routes
│   ├── board/               # Core deliberation engine and board contracts
│   ├── execution/           # Delegated task execution and evidence workflows
│   ├── harness/             # Learning loop, reviews, tuning, ledgers
│   ├── members/             # Board member definitions (*.md)
│   ├── protocols/           # Stage templates and protocol prompts
│   ├── memory/              # State of the Board (SOTB) memory
│   └── cli.py               # Local CLI entrypoint
│
├── hermes/                  # Source-controlled Hermes integration artifacts
│   ├── README.md            # Hermes integration overview and constraints
│   ├── skills/              # Hermes skills used around the board
│   │   ├── agentic-board/           # Invoke the board for high-leverage decisions
│   │   ├── board-memory-update/     # Review SOTB update proposals
│   │   ├── role-gap-review/         # Review repeated capability gaps
│   │   ├── board-decision-to-sprint/# Convert approved decisions into execution work
│   │   └── *-lead-execution/        # Manager-agent execution playbooks
│   └── plugins/agentic_board/       # Future plugin scaffold, not registered yet
│
├── ui/                      # React frontend
├── data/                    # Runtime data: sessions, ledgers, local DBs
├── docs/                    # Architecture, guidebooks, and design notes
├── tests/                   # Test suite
├── start.sh                 # Start local API server and build/serve UI
├── pyproject.toml           # Python package metadata and dependencies
└── requirements.lock        # Locked dependencies
```

## Architecture

Agentic Board runs a 4-stage governance protocol:

1. **Independent analysis**: selected board members respond in parallel.
2. **Peer review**: members critique compacted peer responses.
3. **Chair synthesis**: the chair produces a single board decision.
4. **Verification**: optional quality gate checks the synthesis.

Key system boundaries:

- **`server/board/`** owns governance logic and deliberation.
- **`server/api/`** exposes local HTTP routes for UI and integrations.
- **`server/execution/`** handles approval-gated delegated task workflows.
- **`hermes/`** is an optional operating layer around the board, not a dependency of the Python package.

## Initiatives

Initiatives are the durable operating cycle for the solo-company OS. A board
session can run ad hoc, attach to an existing initiative, or create a draft
initiative. Initiative-owned sessions can produce delegated tasks, artifacts,
memory proposals, and closeout carryovers.

## Running

### Local web app

```bash
./start.sh
```

This builds the UI if needed and starts the local API server on `http://127.0.0.1:8000` by default.

### Local CLI

```bash
uv run python -m server.cli "Your question here"
uv run python -m server.cli --interactive
uv run python -m server.cli --list-members
uv run python -m server.cli --full-board "Major decision"
uv run python -m server.cli --verify --budget "High-impact question"
```

## Hermes Integration

The repository contains **source-controlled Hermes artifacts**, but Hermes is **not** a dependency in `pyproject.toml`.

What is real today:

- **Primary integration path**: Hermes skill → local Agentic Board CLI → saved session JSON.
- **Secondary local path**: Hermes skill → local FastAPI endpoints for SOTB review, role-gap review, and delegated task workflows.
- **Plugin status**: `hermes/plugins/agentic_board/` is a **future scaffold**, not a registered Hermes plugin.

Current repo-backed integration flow:

1. Install and configure Hermes **outside this project** at the user/runtime layer.
2. Make Hermes load the skill files from `hermes/skills/`, or sync individual skills into `~/.hermes/skills/`.
3. Use the `agentic-board` skill to invoke the board via the local CLI:

   ```bash
   .venv/bin/python -m server.cli --verify --budget "<question>"
   ```

4. Read the saved session file from:

   ```text
   data/sessions/<session_id>.json
   ```

5. For follow-up workflows, use the local API routes such as:
   - `POST /sotb/review`
   - `POST /role-gap/review`
   - `GET /sessions/{session_id}/delegation-plan`
   - `POST /delegated-tasks/{task_id}/approve`
   - `POST /delegated-tasks/{task_id}/status`

Important constraints:

- The API is **local-only by default** unless explicit remote auth is added.
- Durable SOTB writes are **not automatic**; the system treats board memory changes as proposals first.
- The plugin scaffold should only be promoted after the skill flow has been proven in real use.
- This repo does **not** provide a documented Hermes install command or a verified CLI command such as `hermes run agentic-board`; those were not evidenced in the codebase.

## Notes on the Current Hermes Design

The current Hermes design is directionally correct, but there are two important caveats:

- The `agentic-board` skill currently reads the saved **full session JSON**, which may pull more context than necessary.
- The API already exposes a compact adapter route at `GET /sessions/{session_id}/adapter`, which looks like the better future contract for Hermes-facing consumption.

Recommended progression:

```text
local CLI skill
  -> local API skill
  -> typed Hermes plugin
  -> remote/gateway usage only after auth and approval gates
```

See `docs/architecture/README.md`, `docs/AGENTIC_BOARD_V2_GUIDEBOOK.md`, and `docs/HERMES_INTEGRATION_GUIDEBOOK.md` for the deeper design rationale.
