# Component Analysis

## Inbound and presentation

### React UI — `ui/src`

- **Owns:** the governance table, portfolio, initiative cockpit, execution,
  performance, and memory views; SSE event presentation.
- **Entry/interface:** `main.tsx` mounts `App.tsx`; `shared/api.ts` is the HTTP/SSE
  client; `shared/types.ts` is the browser-side wire contract.
- **Connects to:** FastAPI only. Domain folders consume shared API/types and do
  not call Python modules directly.
- **Operational note:** `App.tsx` remains the composition root. The built assets
  in `ui/dist` are served by FastAPI when present.
- **Domain surfaces:** board (`ui/src/domains/board`), execution
  (`ui/src/domains/execution`), performance (`ui/src/domains/harness`),
  initiatives (`ui/src/domains/initiatives`), and memory
  (`ui/src/domains/memory`).
- **Slice A limitation:** candidate portfolio review and validation experiments
  have no React surface yet; the implemented founder experience is CLI/local
  record inspection.

### FastAPI API — `server/api`

- **Owns:** application assembly, local/remote access middleware, schemas, static
  UI serving, and route adapters grouped into board, execution, initiatives,
  memory, harness, and system modules.
- **Entry/interface:** `server.api:app`; JSON request/response endpoints and SSE
  streams. Startup optionally registers MCP tools.
- **Connects to:** all user-facing backend domains. Dependencies point inward;
  domain packages must not import the API layer.
- **Risk:** API schemas and persisted session shapes have many consumers and are
  architecture-significant contracts.

### CLIs — `server/cli.py`, `server/discovery/cli.py`

- **Owns:** local board invocation/tuning commands and discovery
  fetch/prepare/synthesize/import, candidate migration/disposition, and bounded
  portfolio-review workflows.
- **Connects to:** board, memory, harness, or discovery packages in process.
- **Boundary:** validated candidates enter one bounded portfolio review. Legacy
  single-candidate promotion remains an explicitly named compatibility path.

### Messaging channels — `server/channels`

- **Owns:** channel configuration loading, command mapping, response rendering,
  and Telegram transport primitives.
- **Connects to:** the board-facing API contract through normalized commands.
- **Status:** integration adapter, not part of deliberation policy.

### Hermes — `hermes`

- **Owns:** source-controlled operating skills for invoking the board, reviewing
  memory/role gaps, turning decisions into sprints, and lead execution.
- **Connects to:** local CLI as the primary path and local API as a secondary
  path. It is not a Python package dependency; the plugin is a future scaffold.

## Governance core

### Board — `server/board`

- **Owns:** member loading, roster selection, prompts, model/provider adapters,
  tools, metrics, stable projections, and structured/live deliberation.
- **Core flow:** intake → classification/routing → independent responses →
  compaction and peer review → chair synthesis → optional verification → stable
  projection and persistence.
- **Connects to:** member/protocol definitions, LLM providers, registered tools,
  memory context/proposals, execution delegation parsing, harness configuration
  and ledger, and session JSON.
- **Internal seams:** `deliberation/` contains orchestration stages;
  `roster/` owns capability metadata; `llm.py` routes providers; `tools.py` is
  the tool registry/executor; `projection.py` stabilizes downstream shape.
- **Risk:** this is the highest-coupling component. Stage output, event, and
  persisted session changes require graph and contract review.

### Definitions — `server/members`, `server/protocols`, board roster/config

- **Owns:** YAML-frontmatter member identities/system prompts, stage prompt
  templates, active roster/capabilities, model defaults, budgets, and thresholds.
- **Connects to:** the board loader/prompt composer and harness configuration.
- **Boundary:** underscore-prefixed member files are shelved. Definitions are
  behavior-bearing configuration and should be reviewed like code.

## Operating domains

### Execution — `server/execution`

- **Owns:** execution units and manager agents, delegated-task lifecycle,
  approval gates, scheduler/runner, artifacts, evidence packets, web search, and
  search caching.
- **Receives:** delegation plans projected from board sessions and direct API
  task commands.
- **Connects to:** board LLM/tool adapters for agent runs, harness hooks/config
  for policy and limits, ventures for scoping, external search, and local task /
  evidence stores.
- **Safety boundary:** task approval and external-action approval are separate;
  board synthesis alone does not authorize side effects.

### Initiatives — `server/initiatives`

- **Owns:** durable time-boxed operating cycles, status transitions, links,
  activation, closeout, founder outcomes, memory proposals, and carryovers.
- **Interface/storage:** API routes over models/store; SQLite-backed local state.
- **Connects to:** sessions and tasks by IDs/links; the API joins initiative task
  views through execution.

### Ventures — `server/ventures`

- **Owns:** venture identity/model and persistence used to isolate work and data.
- **Connects to:** execution scope/scheduling and venture-aware board/memory
  identifiers. Selected portfolio candidates receive idempotent validation ventures.

### Validation experiments — `server/experiments`

- **Owns:** the typed 7-day/14-day validation aggregate, capacity enforcement,
  transition audit rows, automatic validation initiatives, and publisher ports.
- **Storage:** domain-owned tables in the local SQLite database.
- **Safety boundary:** Slice A has only a deterministic fake landing publisher;
  it refuses external publishers and does not enable general always-on execution.
- **Operator surface:** experiments are created by `review-portfolio` and are
  currently inspected through durable local records; a dedicated API/UI is deferred.

### Memory — `server/memory`

- **Owns:** State of the Board reading, governed entries, proposals/reviews,
  per-venture paths, snapshots, rollback, consolidation, and audit metadata.
- **Connects to:** board for context and update proposals; harness config for
  consolidation behavior; LLM only for assisted consolidation/governance paths.
- **Storage:** Markdown SOTB, JSONL index, snapshots, and local metadata store.
- **Safety boundary:** proposals and reviewable diffs precede guarded writes.

### Harness — `server/harness`

- **Owns:** runtime/tunable config, provider/model assignment, routing and
  compaction tuning, outcome ledger, hooks, replay/shadow evaluation, reviews,
  validation, and board-skill loading.
- **Receives:** session metrics/outcomes and founder feedback.
- **Connects to:** board/execution as configuration and policy provider; writes
  ledger/review/config data. Approval and apply are separate API operations.

### Discovery — `server/discovery`

- **Owns:** watchlists, channel adapters, safe HTTP policy, health checks, raw
  collection, deterministic corpus preparation, candidate validation/ranking,
  report rendering, and run storage.
- **Flow:** fetch configured sources → store raw records → prepare a bounded
  agent bundle → external IDE agent analyzes → import validates/enriches/ranks
  → persist schema-v2 candidates → explicit bounded portfolio review → atomically
  record decisions → create selected experiments.
- **Connects to:** public/source APIs, local discovery data, the board portfolio
  contract, and the experiment application service. Collection and import do not
  invoke board LLMs; only the explicit review command crosses that boundary.

### Profiles — `server/profiles`

- **Owns:** loading optional company/profile YAML used to specialize runtime
  behavior and configuration.
- **Connects to:** configuration/roster consumers; it does not orchestrate work.

## Supporting systems

### Evaluation — `evals`

- **Owns:** offline corpus runner, quality signals, metrics, reporting, and eval
  ledger for board behavior.
- **Connects to:** the board orchestrator and harness configuration. It is a
  development/quality consumer, not a production request path.

### Tests — `tests`

- **Owns:** behavioral, provider, API, safety, storage, and architecture
  contracts. Live-provider tests are opt-in.
- **Architecture role:** `test_architecture_docs.py` runs the catalog checker;
  `test_architecture_contract.py` protects dependency direction and endpoints.

## Persistence map

| Owner | Data | Typical location |
| --- | --- | --- |
| Board | Complete deliberation/session records | `data/sessions/*.json` |
| Harness | outcome ledger, reviews, config | SQLite / `data/harness_reviews` / `server/harness/harness_config.json` |
| Execution | tasks, evidence packets, cached search | `data/` domain stores |
| Initiatives | initiatives and links | local SQLite database |
| Ventures | venture records | local SQLite database |
| Memory | SOTB, index, snapshots | `server/memory` defaults and venture data paths |
| Discovery | raw runs, candidates v2, portfolio reviews | discovery store under local runtime data |
| Experiments | validation aggregates and audit events | local SQLite database |

Runtime data is local and generally gitignored. File formats and IDs are
integration contracts even where no database service is involved.
