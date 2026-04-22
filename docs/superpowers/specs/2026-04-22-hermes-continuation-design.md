# Hermes Continuation — Design Spec

**Date:** 2026-04-22
**Status:** Proposed
**Scope:** Plan to continue Hermes-philosophy integration after critical review of `docs/HERMES_INTEGRATION_GUIDEBOOK.md`

## Context

The Hermes Integration Guidebook (`docs/HERMES_INTEGRATION_GUIDEBOOK.md`, 1470 lines, reviewed 2026-04-22) proposes a 9-phase plan to wrap Agentic Board with the Hermes agent runtime. Phases 0–3 are complete; Phases 4–5 are partial; Phases 7–9 are partly built ahead of spec (plugin over-scoped, role-shaped skills added, harness/execution subsystems added).

### Repo state at spec time

| Item | Status |
|---|---|
| `hermes/skills/agentic-board/SKILL.md` | 138 lines, present |
| `hermes/skills/board-decision-to-sprint`, `board-memory-update`, `role-gap-review` | Present |
| `hermes/skills/{operations,product,research,security,strategy,technical}-lead-execution/` | Six ~22-line role-shaped skills |
| `hermes/plugins/agentic_board/plugin.py` | 199 lines, 10 tools (4 governance + 6 execution) |
| `server/harness/` | 2258 lines, 10 files — **deeply wired** to orchestrator, verification, compaction, ledger |
| `server/execution/` | 1081 lines, 7 files — **deeply wired** to orchestrator delegation stage, projection, API, UI panels |
| `data/sessions/` | **0 sessions** — zero real deliberations invoked through the Option A skill |
| `tests/` | 33 contract tests including `test_hermes_skill.py`, `test_hermes_plugin.py` |
| Last 30 commits | All UI focused-boardroom work. Hermes path cold. |

### Critical review findings

**Guidebook diagnosis — mostly accurate:**
- ✅ Role-shaped skills flagged as anti-pattern (§8.4)
- ✅ Plugin over-scoped flagged (§6 Option C Status)
- ✅ Markdown parsing brittleness (§10.3)
- ✅ SOTB vs Hermes memory budget mismatch (§9.5)

**Guidebook misses:**
- ❌ Zero real deliberations logged. Everything after Phase 3 was built on unvalidated scaffolding.
- ❌ Harness + execution are **product surface** (orchestrator, UI), not scope creep to prune.
- ❌ Author was iterating UI for 30 commits while proposing more backend phases.

**Guidebook over-engineers itself:**
- 1470 lines of planning doc.
- Diagnoses scope creep then proposes more scope (Phase 8 compactor, Phase 9 reconciliation, 6 next artifacts).
- `§9.5` Hermes memory compactor = solution for a sync path that has never been exercised (hermes-agent not installed).

**Hermes self-evolution is content-level, not algorithm-level.** Four artifact substrates (skills, memory, session log, tools); runtime is fixed code. Closest analogs: Voyager (skill library), MemGPT (memory). Not DSPy (algorithm).

### Reframe under (y)

Hermes runtime NOT installed. Adopt Hermes *philosophy* via existing repo primitives (skills as markdown, SOTB as compact memory, `data/sessions/` as session log, proposal-→-approval gates). Install `hermes-agent` only if/when cross-platform messaging, Nous Portal tool gateway, or Hermes cron become a real need.

## Goals

- Validate the Option A skill flow via 3 real deliberations before building further.
- Clean up concrete anti-patterns that survived (test gap, orphan filenames, guidebook drift) without removing legitimate product surface.
- Close the Hermes-style self-evolution loop: board members **consume** accumulated artifacts during reasoning and **propose** new artifacts from outcomes.
- Keep `hermes-agent` optional. No install unless a concrete gap justifies it.

## Non-Goals

- Installing `hermes-agent`.
- Algorithm-level evolution (DSPy auto-prompt, RL verifier, fine-tuning). Different philosophy; separate project.
- `server/memory/hermes_projection.py` compactor (§9.5 of guidebook). Deferred indefinitely — no Hermes memory store to write to under (y).
- Plugin deletion. User instruction: keep scaffolded plugin as-is. Revisit only if Hermes is installed.
- Deleting harness or execution subsystems. Both are wired to product (orchestrator + UI).
- Full guidebook rewrite. Light patches only.
- Deleting role-shaped skills. User reframed them as per-role accumulators; retain and rename.
- Plugin tool split (governance vs execution). Moot while Hermes not loading the plugin.
- Neural retrieval (embeddings, cosine). FTS5 keyword is enough pre-PMF.
- Autonomous skill/memory promotion. All writes human-gated.

## Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Hermes runtime install | **No install now.** Adopt concepts via existing primitives. | 0 real sessions; no demonstrated gap. Install when a concrete use case (messaging, Portal tools, cron) arises. |
| `hermes/` directory fate | **Keep.** Dual-purpose: Claude Code skills today, Hermes skills if installed later. | User instruction. Zero-cost preservation. |
| Plugin (`hermes/plugins/agentic_board/`) | **Keep as scaffolded.** No evolution until Hermes installed. | User instruction. Not loaded by anything today. |
| Role-shaped skills | **Keep + rename.** `*-lead-execution/` → `*-lead-playbook/`. | User reframes as per-role accumulators, not duplicates. Rename clarifies intent; drops confusion with `server/execution/`. |
| `server/harness/` and `server/execution/` | **Retain as product surface.** | Wired to orchestrator, verification, compaction, ledger (harness); orchestrator delegation stage, projection, API routes, UI panels (execution). Guidebook misframed these as scope creep. |
| SOTB→Hermes memory compactor (§9.5) | **Deferred indefinitely.** | No target memory store. Under (y), SOTB is its own compact memory; no projection to `~/.hermes/memories/` needed. |
| Sequencing | **C (validate) → B (cleanup) → D (retrieval).** Each track gates the next. | Validation produces corpus + real skill gaps before cleanup or retrieval. Cleanup prepares clean retrieval surface. Retrieval over empty stores is pointless. |
| Retrieval granularity | **Role-playbook per member (D.1)**, then session FTS5 (D.2), then playbook promotion (D.3). | D.1 is deterministic and cheap; D.2 needs non-trivial session corpus (≥10); D.3 closes the evolution loop. |
| Retrieval injection point | **Before Stage 1 per member**; chair also gets playbook at Stage 3. **No retrieval in Stage 2.** | Stage 2 peer review protection — avoid cross-contamination. |

## Tracks

### Track C — Validate (blocks B and D)

**Objective:** produce 3 real deliberations through `hermes/skills/agentic-board/SKILL.md` to generate corpus + skill gap list.

**Invocation protocol:**
1. When a real, board-worthy question arises, Claude Code reads `hermes/skills/agentic-board/SKILL.md` as procedural doc.
2. Claude Code decides: `full_board` / specific `--members` / `--verify`.
3. Run `uv run python -m server.cli --verify --budget "<question>"`.
4. Capture `session_id` from `data/sessions/`.
5. Present decision + SOTB proposal + delegation_plan to user.
6. User approves/rejects each gate.
7. Append to validation log.

**Candidate decision types (user picks from real backlog, not synthetic):**
- UI ship vs iterate (focused-boardroom).
- Who is the first user of Agentic Board? (founder, other founders, internal agents).
- Model mix optimization across deepseek + kimi (moonshot) — which stage on which provider. Introducing a third provider?
- Guardian activation trigger (UI paths handle user data?).
- First real SOTB entry: what belongs in institutional memory vs what doesn't.
- Scope decisions for harness/execution — next feature or freeze?

**Validation log** at `docs/analysis/hermes-validation-log.md`:

```markdown
# Hermes Validation Log

## Session N — YYYY-MM-DD
- session_id: board_...
- query: "..."
- invocation: <exact CLI>
- decision quality: good / partial / bad — 1 sentence why
- SOTB proposal: accepted / edited / rejected — 1 sentence why
- delegation_plan: approved tasks / skipped
- SKILL.md gaps observed: (bullets feeding B and D)
- follow-up action: (what was done after)
```

**Exit criteria:**
- 3 sessions logged with real (not synthetic) decisions.
- SKILL.md gap list drafted.
- ≥1 SOTB write (validates memory gate end-to-end).
- ≥1 rejected SOTB proposal (validates gate actually gates).

**Escape hatch:** if <3 real decisions arise within 6 weeks wall-clock, run what exists and proceed to B/D with log flagged "incomplete validation, revisit."

### Track B — Cleanup (blocks D)

**Objective:** fix concrete anti-patterns that survived; align guidebook with repo reality; prepare clean surface for D.

**Actions:**

| # | Action | Target |
|---|---|---|
| B.1 | Rename + reconcile role-skills | `hermes/skills/{operations,product,research,security,strategy,technical}-lead-execution/` → `*-lead-playbook/` (user-approved pattern β). Then reconcile filenames with actual member IDs (see Open Questions): proposal is to further align to `<member_id>-playbook/` and create empty seed playbooks for `chairperson`, `critic`, `builder`. Update `metadata.name` and `description` inside each `SKILL.md` to reflect "living playbook" intent. |
| B.2 | Test gap audit | Map 33 existing tests → §13 Phase 0 requirements (loader, classifier parsing, compaction extraction, SOTB update parsing, decision projection, session serialization). Write only what's missing. Produce `docs/analysis/phase0-test-coverage.md`. |
| B.3 | Guidebook patches (not rewrite) | `docs/HERMES_INTEGRATION_GUIDEBOOK.md`: §0.5 legitimize harness/execution as product surface; §5 diagram correction; §8.4 override with "retained as per-role accumulators" rationale; §9.5 mark DEFERRED under runtime-free framing; §16 replace next-artifacts list with C→B→D pointer to this spec. |

**Out of scope for B:**
- Plugin changes.
- Harness or execution changes.
- Compactor work.
- Full guidebook rewrite.
- Deleting any subsystem.

**Exit criteria:**
- All 6 role-skills renamed, imports/references updated (grep confirms zero references).
- Phase 0 test coverage matrix committed; any missing tests written.
- Guidebook re-reads consistent with repo reality as of commit.

### Track D — Retrieval (closes evolution loop)

**Objective:** members consume accumulated artifacts during reasoning; chair proposes new artifact writes from outcomes.

**D.1 — Role-playbook injection (required):**
- New module `server/board/retrieval.py`.
- `load_role_playbook(member_id) -> str` reads the member's playbook file under `hermes/skills/` (exact filename convention finalized in B.1 — see Open Questions). Token-capped at ≤500 tokens (use existing compaction utilities if over budget).
- Orchestrator calls it before Stage 1 per member; injects as `## Role Playbook` block in member context.
- Chair gets its own role playbook at Stage 3 (alongside existing SOTB).
- Stage 2 peer review: **no extra retrieval** (prevents cross-contamination).

Exit D.1: every Stage 1 member prompt contains `## Role Playbook` block; token budget enforced; tests confirm injection.

**D.2 — Session retrieval (stretch):**
- Add SQLite FTS5 index over `data/sessions/*.json` (`data/sessions_index.db`). No Hermes dependency.
- `retrieve_relevant_sessions(query, member_id, k=3) -> list[str]` returns compacted snippets, ≤300 tokens per member.
- Optional CLI flag `--retrieve-sessions`.
- Gated on ≥10 sessions in corpus (FTS5 on tiny corpus is noise).

Exit D.2: one deliberation demonstrates cross-session learning (member references prior decision in its reasoning).

**D.3 — Playbook promotion (stretch, evolution closure):**
- After Stage 3 synthesis, chair extracts candidate role-playbook additions (mirror of SOTB proposal).
- Session JSON gets `proposed_playbook_updates: [{role_id, append_text, rationale}]`.
- User approves via new endpoint or UI gate → append to playbook file.
- Identical governance pattern to `memory.proposed_sotb_update`.

Exit D.3: one approved playbook update written in a real session.

**Per-member Stage 1 context overhead budget:** ≤800 tokens (500 playbook + 300 sessions). Safe under deepseek (64K) and kimi (128K) context limits given query + SOTB overhead.

## Sequencing

```
Week 1-6: Track C                          (blocks B, D)
  - Invoke SKILL.md on real decisions as they arise
  - 6-week cap; escape hatch if corpus < 3

Week 6-7: Track B                          (blocks D)
  - B.1 rename role-skills          (half day)
  - B.2 test gap audit              (half day)
  - B.3 guidebook patches           (half day)

Week 7-9: Track D
  - D.1 role-playbook injection     (core, required)
  - D.2 session FTS5 retrieval      (stretch, gated on corpus)
  - D.3 playbook promotion          (stretch, closes loop)
```

C is wall-clock bound by real decisions arriving. B is ~1-1.5 days focused work. D.1 is ~3-5 days; D.2/D.3 are each 2-3 days if undertaken.

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| No real decisions arise during C → plan blocks indefinitely | High | 6-week cap + escape hatch. |
| Role-playbooks stay empty seeds → D.1 adds ceremony without value | Medium | D.3 (promotion flow) is what makes them accumulate. If D.1 ships without D.3, playbooks remain hand-edited; fine for bootstrap, but must ship D.3 within 1-2 deliberations post-D.1. |
| FTS5 index duplicates effort if Hermes installed later | Low | Our FTS5 is over `data/sessions/`; Hermes FTS5 would be over its own sessions. They coexist; our index just becomes pre-Hermes history. |
| Guidebook patches drift again | Medium | Make patches in same commit as code that invalidates them. Treat guidebook as living doc, not canon. |
| Plugin rot while Hermes not installed | Low | Kept as scaffolded per user instruction. Test coverage (`test_hermes_plugin.py`) keeps it compilable. Revisit only on Hermes install. |
| D.1 token overhead busts model context on long queries + full SOTB | Low | 800 token overhead + 2-4K SOTB + query < 10K; deepseek 64K, kimi 128K. Add monitoring; if contexts approach limits, drop session retrieval first. |
| C validation is theater (user manufactures decisions to hit N=3) | Medium | Pick from real backlog only. Log must reflect "what I actually decided, not what I ran to hit the number." |
| Role-playbook retrieval contaminates member independence | Medium | Only own-role playbook loaded per member at Stage 1; no cross-member leakage. Stage 2 peer review gets no retrieval. |

## Exit State

After all three tracks close:

- `data/sessions/` has ≥3 real deliberation artifacts.
- `docs/analysis/hermes-validation-log.md` documents real usage patterns + skill gaps.
- 6 role-skills renamed to `*-lead-playbook/`; guidebook references updated.
- `docs/analysis/phase0-test-coverage.md` proves Phase 0 test coverage complete.
- `docs/HERMES_INTEGRATION_GUIDEBOOK.md` is consistent with repo on 2026-04-22 snapshot; §9.5 marked deferred; §16 pointer to this spec.
- `server/board/retrieval.py` exists and is invoked per member at Stage 1.
- `hermes/skills/<role>-lead-playbook/SKILL.md` files contain real role-specific procedures accumulated from approved deliberations (not seed templates).
- At least one approved `proposed_playbook_updates` write demonstrates the full evolution loop.
- Self-evolution loop closed: members retrieve → deliberate → propose → human approve → accumulate → next deliberation retrieves better context.

Hermes runtime still **not installed.** Install remains optional pending a concrete gap (messaging gateway, Nous Portal tools, cron) that the project actually needs.

## Open Questions (resolvable during implementation)

- **Role-skill → member ID mapping.** Active members: `chairperson, strategist, product, researcher, critic, architect, builder`. Current role-skills: `operations, product, research, security, strategy, technical`. Mismatches: (a) `strategy-lead` vs `strategist` member, (b) `research-lead` vs `researcher` member, (c) `technical-lead` likely → `architect`, (d) no playbook for `chairperson, critic, builder`, (e) `security-lead` maps to shelved `guardian`, (f) `operations-lead` maps to shelved `operator`. B.1 should reconcile: rename to align with member IDs (e.g., `strategist-playbook/`, `architect-playbook/`) and create empty seed playbooks for `chairperson`, `critic`, `builder`. Shelved members' playbooks (`guardian`, `operator`) stay on disk unused until activation. (Proposal: align filenames to `<member_id>-playbook/`; create missing seeds.)
- Does B.1 rename include changing the `metadata.name:` field inside each `SKILL.md`? (Proposal: yes — match new filename and member ID.)
- For D.1, should playbook content be injected into member `system_prompt` or as a separate `## Role Playbook` user-message block? (Proposal: separate block, so system prompt stays stable.)
- For D.3, should the approval UI be CLI-only, web UI, or both? (Proposal: CLI-only for first pass; UI if adoption justifies.)
- How does D.1 behave when a member has no playbook file (e.g., shelved member activated mid-project)? (Proposal: inject empty block with `No accumulated playbook yet` placeholder; no error.)
