# PilotDeck Adoption — Implementation Plans

**Status:** Implementation-ready engineering plans
**Date:** 2026-06-16
**Companion to:** `design/pilotdeck-evaluation.md`

This document turns the seven adoption recommendations into concrete, file-level
plans. Each plan is grounded in the **current** code (verified by reading the
source), states the precise gap versus PilotDeck, and gives new files, function
signatures, schema/migrations, config flags, tests, rollout, and effort.

> **Important correction to the evaluation doc.** A first-pass review described
> SOTB as "a single ≤1000-word markdown blob." That is only the legacy
> `server/memory/sotb.py` path. The live path is
> `server/memory/sotb_governance.py`, which already implements a **structured
> JSONL sidecar** (`SotbEntry`: `entry_id`, `section`, `text`, `created_at`,
> `updated_at`, `confidence`, `expires_at`, `provenance`), freshness checks,
> drift reconciliation, atomic writes, and dark-launched conflict/contradiction
> judges. The board is ~70% of the way to EdgeClaw already. The plans below build
> on that, they do not replace it. Likewise, `server/initiatives/` already
> provides a WorkSpace-like layer, and `server/execution/` already has a full
> task lifecycle — so the true gaps are narrower and cheaper than first stated.

## Current-state map (verified)

| Subsystem | File(s) | What exists | The actual gap |
|---|---|---|---|
| Institutional memory | `server/memory/sotb_governance.py` | Structured entries, provenance, freshness, drift reconcile, dark-launched judges | **No consolidation/dedup/supersession; no snapshot+rollback; judges off; no audit surface; no per-venture scoping** |
| WorkSpace | `server/initiatives/{models,store}.py` | Time-boxed initiatives, links to sessions/tasks/SOTB entries, closeout/carryover | **No persistent venture scope; SOTB + sessions + ledger are global** |
| Execution | `server/execution/{tasks,agents}.py` | Full task lifecycle, manager agents + sub-agent templates, approval/external/hook gates | **No executor — `plan_delegated_task` sets status `running` but nothing runs; no scheduler** |
| Cost | `server/board/metrics.py`, `server/harness/ledger.py` | Actual per-call cost, provider rollup, `total_cost_usd` | **No baseline/counterfactual cost; no savings reporting; no tier routing** |
| Tools | `server/board/tools.py` | Custom `TOOLS` registry, `execute_tool`, `ToolBudget` | **Not MCP-native** |
| Channels | `server/api/` | Web UI + CLI | **No chat channels** |
| Packaging | `hermes/`, `server/harness/skills/` | Skills/plugins exist | **No bundled board "profile/pack"** |

---

# Plan 1 — White-box memory: consolidation + snapshot/rollback + audit

**Priority: ⭐ highest.** Effort: ~4–6 dev-days for 1a–1c; +2 for 1d; +2 for 1e.

### Gap vs PilotDeck EdgeClaw
`apply_sotb_update_governed` is **append-only / log-only** (DC2). It never
supersedes, dedups, moves resolved items, or rewrites markdown. There is no
snapshot, so a bad write is unrecoverable. The conflict/contradiction judges
exist but are `sotb_judge_enabled: false`. EdgeClaw's "Dream Mode" + content-hash
snapshots + one-click rollback are exactly what's missing.

### 1a. Snapshot + rollback (`server/memory/sotb_snapshot.py` — new)
Mirror EdgeClaw's content-hash snapshot. Reuse the existing harness DB.

```python
# server/memory/sotb_snapshot.py
@dataclass
class SotbSnapshot:
    snapshot_id: str          # uuid4
    created_at: str           # iso utc
    reason: str               # "pre_consolidation" | "pre_apply" | "manual"
    md_sha256: str
    index_sha256: str
    md_text: str              # full copy (file is <1000 words; cheap)
    index_json: str           # full JSONL copy
    session_id: str | None

def capture_snapshot(*, reason: str, session_id: str | None = None,
                     md_path=None, index_path=None, db_path=None) -> SotbSnapshot
def list_snapshots(*, limit: int = 20, db_path=None) -> list[dict]
def rollback_to(snapshot_id: str, *, db_path=None) -> dict   # hash-guarded
```
- **Storage:** new table `sotb_snapshots` created in `ledger._ensure_columns`
  (single source of schema truth) — columns mirror the dataclass.
- **Rollback guard (EdgeClaw pattern):** before restoring, recompute current
  `md_sha256`/`index_sha256`. If they don't match the snapshot's *successor*
  state, still allow rollback but flag `manual_edits_since=true` in the result so
  the UI can warn — matching EdgeClaw's "rollback may be unavailable" semantics.
- **Atomicity:** restore writes via the existing `write_sotb_index` (tmp+fsync+
  rename) and an equivalent atomic markdown write helper.

### 1b. Consolidation pass — the "Dream Mode" analogue (`server/memory/sotb_consolidation.py` — new)
This is the deferred "P4.1." Pure-Python clustering first; LLM rewrite gated.

```python
async def consolidate_sotb(*, verify: bool, session_id: str | None = None,
                           md_path=None, index_path=None, db_path=None) -> ConsolidationResult
```
Algorithm:
1. `capture_snapshot(reason="pre_consolidation")`.
2. Load reconciled entries via `read_sotb_index`.
3. **Dedup:** entries with identical `entry_id` already collapse; add
   near-dup detection by reusing `_find_overlapping` (same heuristic the
   contradiction judge uses) within a section. Merge near-dups, keeping the
   higher `confidence` and union of provenance.
4. **Supersession:** when a newer entry contradicts an older one (run the
   existing `_contradiction_judge` only when `verify and sotb_judge_enabled`),
   mark the older `deprecated=true` and move it to a `Resolved` section bullet
   `- [superseded YYYY-MM-DD] <text>`.
5. **Expiry sweep:** reuse `compute_freshness` to drop expired entries
   (already implemented).
6. Rewrite `sotb.md` from the surviving entries (new helper
   `render_md_from_entries(entries)` — inverse of `_parse_markdown_entries`)
   and `write_sotb_index`.
7. Return counts: merged, superseded, expired, kept; write a row to the harness
   ledger (new `record_consolidation` or reuse `record_hook_event` with
   `tool_name="sotb_consolidation"`).

**Trigger:** call from the orchestrator after `apply_sotb_update_governed` when
a counter (entries written since last consolidation, tracked in
`pipeline_state`-style row) crosses a threshold (`hardening.sotb_consolidate_every`,
default 10), OR via a new API endpoint / CLI flag for manual runs.

### 1c. Wire snapshot into the write path
In `apply_sotb_update_governed`, add `capture_snapshot(reason="pre_apply",
session_id=...)` immediately before the markdown/index write. ~3 lines; gives
rollback for every automated write, not just consolidation.

### 1d. Turn on the judges (rollout)
Flip `sotb_judge_enabled` via the harness review/activation machinery
(`snapshot_activation`/`revert_activation` already exist). Shadow-first: run the
judges, log conflicts to `conflicts_logged` (already wired) for N sessions,
review precision in the ledger, then enable supersession in 1b.

### 1e. Audit surface (provenance is captured but invisible)
Add read-only endpoints in a new `server/api/routes/memory.py`:
- `GET /memory/entries` → reconciled `SotbEntry[]` (provenance, confidence, expiry).
- `GET /memory/snapshots` → `list_snapshots()`.
- `POST /memory/rollback/{snapshot_id}` → `rollback_to()`.
- `POST /memory/consolidate` → `consolidate_sotb()`.
Then a small UI panel under `ui/src/` to view/edit/pin entries and roll back.

### Tests
- `tests/memory/test_sotb_snapshot.py`: capture→mutate→rollback roundtrip;
  hash-guard flags manual edits.
- `tests/memory/test_sotb_consolidation.py`: dedup merges provenance; expiry
  sweep; supersession moves to Resolved (judge patched, as existing tests patch
  `server.memory.sotb_governance.query_llm`).
- Reuse the existing governance test patterns.

---

# Plan 2 — Venture (WorkSpace) isolation

**Priority: ⭐ high — do before memory layout ossifies.** Effort: ~3–5 dev-days.

### Gap vs PilotDeck WorkSpace
`server/initiatives/` is WorkSpace-*like* but initiatives are **time-boxed
projects** (7-day default timebox, `draft/active/closed`, closeout/carryover),
not persistent isolated workspaces. SOTB (`_SOTB_PATH` = one `sotb.md`),
sessions (`data/sessions/`), and the ledger are all **global**. A solo founder
running two ventures gets cross-contaminated memory — the exact failure
PilotDeck's white-box isolation solves.

### Design decision
Introduce a **`venture`** layer that *owns* memory + sessions + a ledger scope;
**initiatives nest under a venture** (a venture is the long-lived company/product;
initiatives are its time-boxed pushes). Default venture `"default"` preserves all
current behavior (zero-migration for existing single-venture users).

### Changes
1. **New `server/ventures/{models,store}.py`** (mirror initiatives store style):
   `Venture(id, name, slug, created_at, status)`, table `ventures` in
   `harness_ledger.db`. `slug` is filesystem-safe.
2. **Per-venture memory paths.** Replace module-level `_SOTB_PATH`/`_INDEX_PATH`
   constants in `sotb_governance.py` with a resolver:
   ```python
   def venture_paths(venture_id: str = "default") -> tuple[Path, Path]:
       base = Path(__file__).resolve().parent / "ventures" / venture_id
       return base / "sotb.md", base / "sotb_index.jsonl"
   ```
   `read_sotb_governed` / `apply_sotb_update_governed` already accept
   `md_path`/`index_path` kwargs — thread `venture_id` through and resolve. The
   `"default"` venture keeps `server/memory/sotb.md` for back-compat (special-case
   the resolver).
3. **Session scoping.** `BoardSession.save()` writes to
   `data/sessions/{venture_id}/{session_id}.json`; loaders fall back to the flat
   path for legacy sessions.
4. **Ledger scoping.** Add `venture_id TEXT DEFAULT 'default'` to
   `session_outcomes`, `delegated_tasks`, and `initiatives` via
   `_ensure_columns` (additive, safe). Add optional `venture_id` filter to
   `query_outcomes`/`aggregate`.
5. **Request plumbing.** Add `venture_id` to the deliberate request schema
   (`server/api/schemas.py`), default `"default"`; thread to the orchestrator's
   `read_sotb_governed`/`apply_sotb_update_governed` calls (orchestrator.py
   ~line 1991 and the SOTB-apply site).
6. **CLI.** Add `--venture <id>` to `server/cli.py`.
7. **Cross-venture read (PilotDeck "general mode").** A meta-board endpoint can
   read multiple ventures' SOTB read-only by iterating `venture_paths`.

### Migration
Purely additive columns + a one-time backfill setting existing rows to
`venture_id='default'` (run inside `_ensure_columns` when the column is first
added). No destructive changes.

### Tests
- `tests/ventures/test_isolation.py`: two ventures, write SOTB to A, assert B
  unaffected; session files land under the right subdir; ledger filters by venture.

---

# Plan 3 — Bounded always-on execution: the task runner

**Priority: ⭐ high — turns advisor into operator.** Effort: ~5–8 dev-days
(runner ~3–4, scheduler ~2–3, tests/rollout ~1).

### Gap vs PilotDeck always-on
The board produces excellent delegation plans, but **nothing executes them**.
`plan_delegated_task` (tasks.py) builds a `subtask_plan` and flips status to
`running` — then stops. There is no code that invokes the manager agent or
sub-agent templates, produces artifacts, or completes a task. PilotDeck's
`DiscoveryScheduler` (gates → isolated workspace → bounded execution → report)
is the blueprint. We start with the *execution* half (run already-approved
tasks), not open-ended discovery.

### 3a. The executor (`server/execution/runner.py` — new)
```python
@dataclass
class RunnerBudget:
    max_turns: int = 12
    max_tool_calls: int = 40
    wall_seconds_max: int = 1200
    max_parallel_subagents: int = 3   # capped by agent.max_parallel_subagents

async def run_task(task_id: str, *, budget: RunnerBudget | None = None,
                   db_path=None) -> dict
```
Flow (reusing existing primitives):
1. Load task (`get_delegated_task`); require `status in {approved, running}`.
   **Refuse** if `external_action_required and not external_action_approved`
   (gate already modeled in tasks.py) — deny destructive/outward steps, matching
   PilotDeck's deny-rules.
2. Ensure a subtask plan (`task["subtask_plan"]` or `default_subtask_plan`).
3. For each `Subtask`, run a bounded **manager/sub-agent turn**:
   - Build the prompt from `ExecutionAgent.system_prompt` + subtask
     `objective`/`output_contract`.
   - Allowed tools = intersection of `agent.allowed_tools` /
     `template.allowed_tools` with the board `TOOLS` registry, converted via
     `Tool.to_openai_schema()`.
   - Drive `query_llm(model, messages, tools=..., max_tokens=...)` in a loop;
     dispatch tool calls through the existing `execute_tool(...)`; stop on
     no-more-tool-calls or budget exhaustion (turns/tool-calls/wall-clock).
   - Run up to `max_parallel_subagents` subtasks with `asyncio.gather`.
4. **Land deliverables as files** (PilotDeck "results as files on disk"):
   write each subtask output to
   `data/artifacts/{venture_id}/{task_id}/{subtask_id}.md`; record via
   `attach_task_artifact(task_id, artifact=path)`.
5. Manager synthesizes a `result_summary`; call
   `update_delegated_task_status(task_id, status="completed",
   manager_agent_id=..., result_summary=..., artifacts=[...])` (the assigned-
   manager guard already exists). On failure/budget-exhaust → `"blocked"` with
   `status_detail`.
6. **Strong-main/light-sub (ties into Plan 4):** manager turn uses a mid model;
   sub-agents use a cheap model (config `execution.manager_model` /
   `execution.subagent_model`).

**Safety reuse:** every state change already routes through `_hook_gate_sync`
(deny hooks) and `record_hook_event`. The bundled
`rate_limit_delegated_tasks.py` hook already exists — extend it for the runner.

### 3b. The scheduler (`server/execution/scheduler.py` — new)
Port PilotDeck's gate-first, deterministic scheduler.
```python
@dataclass
class SchedulerGates:
    feature_enabled: bool
    daily_budget: int = 6           # runs/day/venture
    cooldown_seconds: int = 1800
    max_concurrent: int = 2
    quiet_if_user_active_seconds: int = 300

async def tick(*, now=None, db_path=None) -> list[dict]   # fires eligible tasks
def run_forever(interval_seconds: int = 300)              # asyncio loop
```
Gate order (first-to-block wins, pure function `evaluate_gates`): feature off →
venture closed → daily budget hit (count runs in `hook_events`/ledger) →
cooldown not elapsed → max-concurrent reached → recent user activity. Eligible =
tasks with `status="approved"` and satisfied `dependencies`. Acquire a per-task
lock row (reuse `hook_events` or a `task_runs` table) to prevent double-fire.

**Process model:** an opt-in background loop started from `start.sh`/CLI
(`uv run python -m server.cli --always-on`) or an APScheduler-style thread inside
the FastAPI app, off by default (`execution.always_on_enabled: false`).

### 3c. Config (add to `harness_config.json` under a new `execution` block)
```json
"execution": {
  "always_on_enabled": false,
  "manager_model": "qwen/qwen3.6-plus-2026-04-02",
  "subagent_model": "qwen/qwen3.6-flash",
  "daily_budget_per_venture": 6,
  "cooldown_seconds": 1800,
  "max_concurrent_runs": 2,
  "runner_max_turns": 12,
  "runner_max_tool_calls": 40,
  "runner_wall_seconds_max": 1200
}
```

### 3d. API/UI
- `POST /tasks/{task_id}/run` (manual fire), `GET /tasks/{task_id}/run-status`.
- Surface artifacts + `result_summary` in the existing delegation-plan view.

### Tests
- `tests/execution/test_runner.py`: stub `query_llm`; assert a 2-subtask task
  produces 2 artifacts, completes, and respects budget caps; external-action
  task without approval is refused.
- `tests/execution/test_scheduler.py`: gate matrix (each gate blocks in order);
  no double-fire under concurrent ticks.

### Rollout
Manual-fire endpoint first; background loop dark (`always_on_enabled:false`);
enable per-venture once artifact quality is reviewed.

---

# Plan 4 — Routing economics: baseline-savings + tiered fan-out

**Priority: high.** Effort: ~2–3 dev-days (4a–4b), +2 (4c).

### Gap
`metrics.py` computes *actual* cost. There is no **counterfactual baseline**
("what all-flagship would have cost"), so savings are unprovable, and the council
always fans out to the full model set regardless of difficulty.

### 4a. Baseline cost in metrics
Add to `SessionMetrics`:
```python
def baseline_cost_estimate(self, baseline_model: str) -> float:
    return sum(_estimate_cost(baseline_model, c.input_tokens, c.output_tokens)
               for c in self.calls)
def savings(self, baseline_model: str) -> dict:   # baseline, actual, saved, pct
```
`baseline_model` defaults to `get_chairman_model()` (the flagship). Add the
three numbers to `summary()`.

### 4b. Persist + report savings
- Ledger: add `baseline_cost_usd REAL` and `cost_saved_usd REAL` to
  `session_outcomes` via `_ensure_columns`; populate in `record_session` from
  `metrics.savings(...)`. Add both to `_NUMERIC_COLUMNS` so existing
  `aggregate`/`rolling_stats` work unchanged.
- `GET /metrics/summary` already exists — extend its payload with cumulative
  `total_saved_usd` and a savings %.

### 4c. Tiered fan-out (the real cost lever)
The classifier (`server/board/deliberation/classifier.py`) already yields
`complexity`. Use it to scale the council:
- `simple` → chair-only or 1 council member (cheap model).
- `moderate` → current behavior.
- `complex` → full board + verify.
Implement as a routing table in `model_assignment.py` (which already does
per-member model overrides) keyed by `complexity`. This is the board-native
analogue of PilotDeck's token-saver judge — and it reuses an existing signal, so
no new judge LLM call is needed. PilotDeck's session-sticky caching maps to our
already-discrete sessions (no carryover needed).

### Tests
- `tests/board/test_metrics_baseline.py`: savings math; zero when all calls use
  the baseline model.
- `tests/board/test_tiered_fanout.py`: simple query invokes ≤1 council member.

---

# Plan 5 — MCP-native tools

**Priority: medium.** Effort: ~3–4 dev-days.

### Gap
`server/board/tools.py` is a hand-rolled registry (`TOOLS: dict[str, Tool]`).
PilotDeck treats MCP as a first-class tool source, inheriting the whole
ecosystem. The board's `Tool` abstraction (name, description, JSON-schema
`parameters`, async `handler`, `to_openai_schema()`) is already MCP-shaped — the
bridge is small.

### Plan
1. **New `server/board/mcp_client.py`:** connect to configured MCP servers
   (stdio + streamable-http) using the official Python MCP SDK; `list_tools()`
   per server.
2. **Bridge:** for each MCP tool, construct a `Tool` whose `parameters` is the
   MCP `inputSchema` and whose `handler` calls the MCP `call_tool` and wraps the
   result in `ToolResult(content_for_model=..., summary=..., cost_units=...)`.
   Register into `TOOLS` under a namespaced name (`mcp__<server>__<tool>`),
   exactly the convention this environment already uses.
3. **Budget/permission:** MCP tools flow through the existing `execute_tool`
   path, so `ToolBudget` and the hook gates apply unchanged. Mark MCP tools
   read-only vs. effectful so deny-hooks can gate side effects.
4. **Config:** `mcp_servers` block in `.env`/config listing server specs;
   `perSession` lifecycle optional (PilotDeck pattern).
5. **Lifecycle:** start MCP clients at app startup (`server/api/app.py`),
   bounded connect concurrency; per-server failures are non-fatal (log + skip),
   matching PilotDeck's resilience.

### Tests
- `tests/board/test_mcp_bridge.py`: a mock stdio MCP server's tool appears in
  `TOOLS`, executes via `execute_tool`, and respects the budget.

---

# Plan 6 — Multi-channel reach

**Priority: medium-low (after core is solid).** Effort: ~2 days protocol +
~1–2/channel.

### Gap
Web UI + CLI only. PilotDeck reaches the founder on 20+ channels via a clean
`ChannelAdapter` protocol (interface + per-channel session mapper + renderer).

### Plan
1. **New `server/channels/protocol.py`:** Python port of the adapter contract:
   ```python
   class ChannelAdapter(Protocol):
       channel_key: str
       async def start(self, deps: ChannelDeps) -> None: ...
   ```
   `ChannelDeps` carries a `deliberate` callable + a renderer.
2. **Session mapper:** map channel-native (user, thread) → board `session_id`
   (+ `venture_id` from Plan 2), so a Telegram thread resumes a board session.
3. **Renderer:** format the secretary's executive brief / decision projection
   (`server/board/projection.py` already produces a stable shape) into
   channel-native output (Markdown for Telegram, blocks for Slack).
4. **Start with two:** Telegram (long-poll, trivial) and inbound **email**
   (re-uses the brief). Each is ~150–250 LOC following the protocol.
5. **Long deliberations:** ack immediately, run async, post the brief when ready
   — pairs naturally with Plan 3's background execution.

### Tests
- `tests/channels/test_protocol.py`: a fake channel round-trips a query →
  `deliberate` → rendered brief; session mapper resumes the same `session_id`.

---

# Plan 7 — Packaged board "profiles" / products

**Priority: low (productization).** Effort: ~2–3 dev-days.

### Gap
Members are markdown and `hermes/`/`server/harness/skills/` exist, but there's no
single packaged, switchable board configuration. PilotDeck's `plugin.json` +
scoped skills + "products" bundles let you template and distribute whole configs.

### Plan
1. **`server/profiles/<name>/profile.yaml`:** declares `members` (paths under
   `server/members`), `roster` overlay (`server/board/roster/roster.yaml`),
   `harness_config` overrides, and optional `branding`.
2. **Loader `server/profiles/loader.py`:** merge a profile over defaults at
   startup; selected via `BOARD_PROFILE` env or `--profile` CLI flag, and
   scoped per **venture** (Plan 2) so different ventures run different boards
   ("SaaS pre-PMF board" vs "hardware board").
3. **Packaging:** a profile is a directory; ship `profiles/_example/` mirroring
   PilotDeck's `products/_example/`. Distribution = copy/symlink the directory.

### Tests
- `tests/profiles/test_loader.py`: a profile overlay changes the active roster
  and a harness flag without touching defaults.

---

# Sequencing & dependencies

```
Plan 2 (ventures) ──┬─► Plan 1 (memory: scope-aware) 
                    ├─► Plan 3 (runner: per-venture artifacts/budgets)
                    └─► Plan 7 (per-venture profiles)
Plan 4 (routing economics) ──► feeds Plan 3 (strong-main/light-sub)
Plan 5 (MCP) ── independent (do alongside 3; runner gains tools)
Plan 6 (channels) ── last; depends on nothing but benefits from 3
```

**Recommended order:** 2 → 1 → 3 → 4 → 5 → 6 → 7. Plan 2 is cheap and unblocks
clean scoping for 1/3/7, so it goes first even though memory (1) is the highest
*value*. Each plan is independently shippable behind a default-off flag, matching
this codebase's existing dark-launch discipline (`hardening.*_enabled`,
`snapshot_activation`/`revert_activation`).

# Cross-cutting conventions to honor (observed in-repo)
- **Additive SQLite migrations only**, centralized in `ledger._ensure_columns`.
- **Atomic writes** (tmp+fsync+rename) as in `write_sotb_index`.
- **Never-raise side effects:** judges/tools swallow provider errors and degrade
  (see `_detect_query_conflicts`). Runner/scheduler must do the same.
- **Hook gates on every effectful op** (`_hook_gate_sync` + `record_hook_event`).
- **Dark-launch flags default false**, promoted via the review/activation ledger.
- **Tests patch `query_llm` at the module that imports it** (e.g.
  `server.memory.sotb_governance.query_llm`).
