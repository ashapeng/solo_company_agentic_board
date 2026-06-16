# PilotDeck Evaluation — What the Solo Company Board Should Adopt

**Status:** Proposal / design reference
**Date:** 2026-06-16
**Author:** generated from a structured code-level review of both repositories
**Subject:** Critical comparison of [OpenBMB/PilotDeck](https://github.com/ashapeng/PilotDeck) against this project (the Agentic Board), and a prioritized plan for which of PilotDeck's strengths to absorb.

---

## 0. TL;DR

PilotDeck and this project are **not competitors** — they sit at different layers.

- **PilotDeck is a runtime** (an "agent operating system"): per-project isolation, structured memory, smart routing, always-on background execution, MCP-native tools, and 20+ messaging channels.
- **The Agentic Board is a decision brain**: an adversarial, multi-agent deliberation engine with claim atomization, contradiction detection, peer review, a blinded verifier, and forced-revision loops.

The board's deliberation *quality* is its moat and is **ahead** of anything in PilotDeck. The recommendation is therefore **not** to copy PilotDeck wholesale, but to bolt its *runtime* strengths onto our *brain*. In priority order:

1. **White-box memory** to replace the single `sotb.md` blob — highest leverage.
2. **WorkSpace isolation** → multi-venture support.
3. **Bounded always-on task runner** → close the decision→execution loop.
4. **Routing economics** (baseline-savings reporting + strong-main/light-sub).
5. **MCP-native tools.**
6. **Multi-channel reach.**
7. **Packaged skills / "products"** for distribution.

---

## 1. Assessment of PilotDeck

PilotDeck (Tsinghua THUNLP / ModelBest / OpenBMB; AGPL-3.0; ~976 files; TypeScript / React / Ink) is organized around the **WorkSpace** — per-project isolation of files, memory, and skills. It is MCP-native and runs the same agent across CLI, TUI, web, and 20+ chat channels. Four pillars carry the product.

### 1.1 White-box memory (EdgeClaw)
- **Pipeline:** dialogue turns captured into a SQLite `l0_sessions` table → a heartbeat indexer calls an LLM extractor to classify turns and emit structured **memory candidates** → candidates persisted as **frontmatter-markdown files** scoped by `Project/`, `Feedback/`, `UserIdentity/` → a `ReasoningRetriever` ranks and injects memory as `<memory-context>` blocks.
- **Dream Mode:** a periodic consolidation pass clusters, deduplicates, and rewrites memory files. Before it runs, `captureLiveMemorySnapshot()` records **content hashes** of every file; `rollbackLastDreamSnapshot()` provides **one-click rollback** with a hash guard (rollback is refused if the user manually edited memory in between).
- **Auditability:** per-query case traces, per-index traces, and per-dream traces — generation → extraction → storage → retrieval is fully inspectable and editable.
- **Storage:** hybrid SQLite (pending capture) + markdown (human-readable, git-friendly memory).
- **Verdict:** production-grade and genuinely novel. The strongest single idea in the repo.

### 1.2 Smart Routing
- A **token-saver judge** classifies each turn into `simple | medium | complex | reasoning`, **session-sticky** (cached ~1h) so consecutive turns don't re-pay for judging, with explicit handling of short continuations ("ok", "continue") so they inherit the prior tier.
- **Strong-main + light-sub:** `complex` tier triggers an orchestration prompt that turns the main (flagship) model into a planner that delegates execution to cheaper sub-agents. Their published numbers: ~70–77% cost reduction at equal or better quality.
- **Cost tracking:** append-only JSONL with per-record `cost` **and** `baselineCost` (what the default flagship would have cost), enabling provable savings dashboards.

### 1.3 Always-on background execution
- `DiscoveryScheduler` fires on an interval, gated by a **9-gate safety model** (feature/project enabled, dir exists, dormancy, no active user, cooldown ≥60 min, daily budget ≈4 runs, lock file).
- A run is a 5-phase pipeline: **discover → isolated workspace (git worktree) → bounded execution → markdown report → optional apply**, with deny-rules (`git push` blocked), `excludeTools` (no blocking prompts), max turns/tools, timeouts, and a circuit breaker.
- **Verdict:** a safety-first blueprint for autonomy.

### 1.4 Extensibility
- `plugin.json` manifests with `builtin | global | project` scope; contribution types for `command | hook | tool | prompt | mcp | permission_rule`.
- Scoped `SKILL.md` skills addressed by `(scope, slug)` with the manager owning disk layout.
- **MCP as a contribution type** — plugins declare MCP servers and the runtime wires them in.
- A **"products"** concept: per-customer bundles of plugins + `config/pilotdeck.yaml` + `brand/theme.json`.

### 1.5 Honest limitation
PilotDeck's *per-decision* reasoning is a single agent loop. It has breadth but no notion of deliberation quality, adversarial review, or verification.

---

## 2. The Difference

| Dimension | PilotDeck | Agentic Board (this repo) |
|---|---|---|
| Layer / purpose | General agent OS / runtime | Vertical: board-of-directors deliberation |
| Core IP | Memory + routing + autonomy + channels | **Adversarial multi-agent epistemics** |
| Interaction | Continuous, always-on assistant | Discrete request → deliberation → decision |
| Memory | Structured, scoped, editable, rollback-able store | **Single ≤1000-word `server/memory/sotb.md` blob** |
| Autonomy | Proactive background execution | Request/response only |
| Multi-tenancy | Per-WorkSpace isolation | **Single roster, single SOTB, no venture isolation** |
| Cost control | Tier routing + baseline-savings reporting | Fixed multi-model fan-out; cost tracked, not minimized |
| Tools | MCP-native (whole ecosystem) | Custom in-process registry (~15 tools) |
| Reach | 20+ channels | Web UI + CLI |
| Execution | Runs work, lands files on disk | Generates delegation plans (`tasks.db`) that **never fire** |
| Stack | TS / React / Ink / Node | Python / FastAPI / React |
| Size | ~976 files | ~269 files |

**Where the board is ahead** (and must not regress): claim atomization, cross-member contradiction detection, anonymized peer review, blinded verifier, forced-revision loops (P1–P5b), and the harness ledger. PilotDeck has no equivalent.

---

## 3. Strengths to Adopt (prioritized)

Ranked by *impact for a solo founder × fit with current architecture*. Each item names the concrete files it touches.

### ⭐ 1. White-box memory to replace the SOTB blob — highest leverage
**Gap:** institutional memory is one markdown file (`server/memory/sotb.md`, ≤1000 words) and the SOTB *judges* are dark-launched (`server/board/.../sotb_governance.py`). Memory is the thinnest part of a system whose entire premise is cross-session institutional memory.

**Adopt from PilotDeck:**
- Convert SOTB from one blob → a **directory of typed entries** (frontmatter markdown): `decision | constraint | assumption | market-fact`, each with `created_by_session`, `confidence`, `updated_at`, `deprecated`.
- Add a **consolidation pass** (Dream-Mode analogue) after N sessions to cluster/dedupe/rewrite.
- **Snapshot-before-write** with content hashes so a bad synthesis is reversible.
- A derived `MEMORY.md` manifest for retrieval.

**Payoff:** finally gives the dark-launched P4 governance real structure to act on; per-entry provenance makes "why did the board believe X" answerable and editable.

### ⭐ 2. WorkSpace isolation → multi-venture support
**Gap:** one roster, one SOTB, one session pool. A solo founder usually runs more than one thing.

**Adopt:** introduce a `venture_id` (PilotDeck's WorkSpace) scoping `data/sessions/`, the harness ledger, `tasks.db`, and SOTB. Reuse PilotDeck's "general vs single" workspace mode idea so a meta-board can also read across ventures read-only.

**Payoff:** small structural change, large surface-area unlock. Do it **before** the memory layout ossifies.

### ⭐ 3. Bounded always-on task runner → close the decision→execution loop
**Gap:** the board produces excellent delegation plans (`server/execution/tasks.py`, manager agents) that then sit inert in `tasks.db`. There is no runner.

**Adopt incrementally:** start with a scheduler that executes **already-approved** delegation tasks (not open-ended discovery), reusing existing manager-agent definitions, wrapped in PilotDeck's safety bounds: max turns/tools, daily budget, deny destructive ops, circuit breaker, isolated workspace, markdown report back into the session. Graduate to proactive discovery later.

**Payoff:** turns the board from advisor into operator — the single biggest *product* gap.

### 4. Routing economics — baseline-savings + strong-main/light-sub
**Gap:** we already classify queries and assign per-member models, but we fan out to multiple council models at fixed cost and never quantify savings.

**Adopt:**
- Add `baseline_cost` next to `cost` in `server/harness/ledger.py` and `server/board/metrics.py` (what an all-flagship run would have cost) to *prove* savings.
- Apply **strong-main/light-sub** to the execution manager agents: cheap sub-agents do the work, flagship only plans.

### 5. Go MCP-native for tools
**Gap:** the tool registry (`server/board/tools.py`) is hand-rolled and capped at ~15 tools.

**Adopt:** treat MCP as a first-class tool source. We already run inside an MCP-rich environment; inheriting the MCP ecosystem beats hand-coding each tool.

### 6. Multi-channel reach
**Gap:** web UI + CLI only. A solo founder is mobile.

**Adopt:** PilotDeck's `ChannelAdapter` protocol (one interface + per-channel session mapper + renderer) to let the founder "ask the board" from Telegram/Slack/email and receive the secretary's brief back. Lower priority than 1–3 but high product value once the core is solid.

### 7. Packaged skills / "products"
**Gap:** members are markdown (already nice) but there's no packaged, distributable board configuration.

**Adopt:** `plugin.json` + scoped `SKILL.md` + "products" bundles to template and distribute board configs (e.g. "SaaS pre-PMF board" vs "hardware board") — natural if the board is ever productized for other founders.

---

> **Implementation plans:** see the companion `design/pilotdeck-adoption-implementation.md`
> for file-level, implementation-ready plans for all seven items (grounded in the
> actual code — note that the SOTB, initiatives, and execution subsystems are more
> built-out than this evaluation's first pass suggested).

## 4. Recommended sequencing

1. **Memory overhaul** (#1) — foundational; unblocks our own dark-launched governance.
2. **Venture isolation** (#2) — do it before memory ossifies.
3. **Bounded task runner** (#3) — advisor → operator.
4. **Routing economics + MCP** (#4, #5) — efficiency and capability.
5. **Channels + product packaging** (#6, #7) — reach and distribution.

## 5. What NOT to copy
- PilotDeck's **single-agent loop** — it's a downgrade from our deliberation engine.
- **20-channel breadth** before one venture is humming.
- The **generic-OS sprawl** (~976 files). Keep the board focused; absorb runtime strengths surgically, don't dilute the brain.

---

## Appendix — Method

This evaluation came from five code-level "interviews": four into PilotDeck (memory/EdgeClaw, router/model/cost, always-on/agent core, extensions/skills/channels) and one into the full board architecture. File paths above are accurate to the state of each repo at the time of review.
