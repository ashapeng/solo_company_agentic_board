# Agentic Board

A council of world-expert AI agents that deliberate as a company board of directors.

## Project Structure

```
├── server/                  ← Backend
│   ├── api/                 FastAPI app + route modules by domain
│   ├── cli.py               CLI entry point
│   ├── board/               Governance deliberation domain
│   │   ├── deliberation/    4-stage pipeline, routing, compaction, verification
│   │   ├── roster/          Stage profiles and capability routing
│   │   ├── config.py        Model config, member loading
│   │   ├── llm.py           Native provider/OpenRouter API client
│   │   ├── metrics.py       Token and cost tracking
│   │   ├── projection.py    Stable session adapter/projection
│   │   └── loader.py        Member markdown parser
│   ├── harness/             Learning loop: config, ledger, tuners, reviews
│   ├── execution/           Execution units, manager agents, delegated tasks
│   ├── members/             Member definitions (*.md)
│   ├── protocols/           Stage templates (*.md)
│   └── memory/              SOTB (institutional memory)
│
├── ui/                      ← Frontend
│   ├── index.html           Single-page app
│   └── src/                 React app, domain entrypoints, shared API/types
│
├── data/                    ← Runtime (gitignored)
│   └── sessions/            Saved deliberation JSON
│
└── docs/                    ← Documentation
    └── architecture/         Domain map, runtime flow, extension guide
```

See `docs/architecture/README.md` for the current domain boundaries and
extension rules.

## Architecture

4-stage deliberation protocol (inspired by Karpathy's LLM Council):

1. **Stage 1 — Independent Analysis**: Council members analyze the query independently (parallel). No cross-contamination.
2. **Stage 2 — Peer Review**: Each member reviews anonymized, compacted responses from all others. They challenge, rank, and build upon peers.
3. **Stage 3 — Chairman Synthesis**: The Chairperson compiles all input into a single authoritative board decision (with SOTB context).
4. **Stage 4 — Verification** (opt-in): Quality gate scores the synthesis and triggers revision if needed.

**Key concepts**: Query classification routes to relevant members. Compaction reduces token usage between stages. SOTB (State of the Board) provides institutional memory across sessions.

## Board Members (7) — Early-Stage Market/Product Focus

| ID | Title | Role | Priority |
|----|-------|------|----------|
| chairperson | Chairperson | CEO / Product Decision Synthesis | 100 |
| strategist | Chief Strategist | CSO / Market Strategy & Evidence | 90 |
| product | Product Lead | CPO / Product Strategy & Definition | 85 |
| researcher | Customer Researcher | Voice of Customer / User Research | 80 |
| critic | Devil's Advocate | Red Team / Contrarian Analysis | 75 |
| architect | Technical Feasibility Lead | CTO / Prototyping & Feasibility | 65 |
| builder | Prototype Engineer | Builder / Rapid Validation | 60 |

Shelved (post-PMF): `_guardian.md` (CISO), `_operator.md` (Operations Lead)

Members are defined in `server/members/*.md` files (YAML frontmatter + markdown system prompt). Files prefixed with `_` are shelved and not loaded.

## Running

```bash
# Web UI (recommended for demos)
./start.sh                                        # → http://localhost:8000

# CLI
uv run python -m server.cli "Your question here"
uv run python -m server.cli --interactive
uv run python -m server.cli --list-members
uv run python -m server.cli --members strategist,product "Product question"
uv run python -m server.cli --full-board "Major decision"
uv run python -m server.cli --verify --budget "Question with verification"

# API only
uv run uvicorn server.api:app --reload --port 8000
```

### CLI Flags

| Flag | Description |
|------|-------------|
| `--interactive, -i` | Interactive REPL mode |
| `--list-members, -l` | Show board member table |
| `--verbose, -v` | Show Stage 1 individual responses |
| `--members, -m IDS` | Comma-separated member IDs to invoke |
| `--full-board, -f` | Skip classifier, invoke all members |
| `--verify` | Enable Stage 4 verification |
| `--budget` | Show token usage and cost breakdown |

### API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve frontend UI |
| GET | `/members` | List all board members |
| POST | `/deliberate` | Full board deliberation |
| POST | `/deliberate/stream` | SSE streaming deliberation |
| GET | `/sessions` | List saved sessions |
| GET | `/sessions/{id}` | Retrieve a session |
| GET | `/sotb` | Read State of the Board |
| PUT | `/sotb` | Update SOTB manually |
| GET | `/metrics/summary` | Last session metrics |

## Config

- Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY` and `MOONSHOT_API_KEY`
- Edit `server/board/config.py` to customize models
- Native SDK routing is supported with explicit prefixes:
  `glm/<model>` or `zai/<model>` uses Z.AI, `qwen/<model>` uses DashScope,
  `deepseek/<model>` uses DeepSeek via the OpenAI SDK, and `kimi/<model>` uses Kimi via the OpenAI SDK.
  Defaults use `kimi/kimi-k2.6` (chair), `[deepseek/deepseek-v4-pro, glm/glm-5.1, qwen/qwen3.6-max-preview]` (council, round-robin), `gemini/gemini-2.5-flash` (classifier, free tier), and `deepseek/deepseek-v4-pro` (verifier, ≠ chair). Use `openrouter:<model_id>` to force OpenRouter for a provider-shaped model ID.
- Add/edit members in `server/members/*.md`
- Verifier must use a different provider than the chairman. To run both on
  the same provider during local experimentation, set
  `AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1`.
