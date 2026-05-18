# Harness Cross-Cutting Expansion — Design Spec

- **Status**: Draft (awaiting user review before implementation planning)
- **Date**: 2026-05-18
- **Owner**: Peng
- **Drives**: turning `server/harness/` from a learning-loop into the project's control plane by absorbing three patterns borrowed from OpenHarness (HKUDS): static dry-run, pre/post-tool hooks, and member-declared skills.
- **Branch**: TBD (work to be planned in writing-plans phase)
- **Companion documents**:
  - In-conversation comparison: OpenHarness vs `server/harness/` (rendered to `/tmp/openharness_vs_serverharness.html` during brainstorming)

## 1. Context & motivation

`server/harness/` today is a tuning-and-review loop wrapped around the Board's
4-stage deliberation pipeline. It records every session into SQLite, runs four
data-driven tuners (token budgets, verification thresholds, routing/compaction,
model picks), gates changes behind a `HarnessReview` artifact, shadow-watches
the next ten sessions, and auto-reverts on regression. It does not itself
run any LLM call, register any tool, or carry any cross-cutting infrastructure.

Three patterns from OpenHarness (HKUDS) would meaningfully strengthen this
project if folded into the harness as cross-cutting infrastructure:

1. **Static dry-run.** OpenHarness's `--dry-run` resolves settings without
   spending any tokens; we can do the equivalent for `HarnessConfig` so that
   `apply_harness_review` never writes a structurally broken config.
2. **Pre/post-tool hooks.** OpenHarness wraps every tool call in a `PreToolUse`
   / `PostToolUse` lifecycle. The Board's `server/execution/` layer has real
   tool-like surfaces today (`web_search`, delegated tasks) with no gate
   beyond ad-hoc code in each call site.
3. **Skills.** OpenHarness lets agents pull in on-demand markdown knowledge
   bundles. Board members today have a single static system prompt; there is no
   mechanism for a member to declare "use this method when answering pricing
   questions" without editing the member file.

Treating the harness as the home for all three turns it into the project's
control plane: a single place to validate configs before they ship, gate tool
calls before they run, and inject member knowledge before stages execute. The
existing tuner / ledger / review / shadow loop stays intact; this spec is
purely additive.

A fourth borrow — MCP transport — is **explicitly deferred** until a real
external-tool consumer exists. Building it speculatively would be scaffolding
without callers.

## 2. Goals & non-goals

### Goals

1. A pure-Python validator catches structurally broken `HarnessConfig`
   candidates before `apply_harness_review` writes them. Zero LLM calls.
2. A hook registry lets pre-hooks deny a tool call (with a reason) and lets
   pre- and post-hooks log metadata to a new ledger table. Wired into
   `server/execution/web_search.py` and `server/execution/tasks.py`.
3. Board members can declare named skills in their YAML frontmatter; the
   harness loads those skills' markdown bodies and appends them to the
   member's system prompt at Stage 1 and Stage 2 entry.
4. Each subsystem records what it did in the ledger so future tuners can
   learn from its behavior.
5. Every change is additive: existing files in `server/harness/`,
   `server/execution/`, and `server/board/` keep their current public API.

### Non-goals (V1)

- MCP transport. No external tool consumer exists; deferred.
- Modify-power hooks (rewriting tool requests or responses). Observe + block
  only. Mutation hooks make debugging tool outputs intractable.
- Skill auto-discovery or model-invoked skills. Members declare statically.
- Per-query-type skill filtering (member declares + classifier filters).
  Deferred until member-declared proves too coarse.
- Replay-based dry-run. `shadow.py` already catches regressions post-apply;
  replay-during-dry-run overlaps without paying for itself.
- UI surfaces beyond CLI and HTTP API. The existing review / SOTB / metrics
  endpoints stay sufficient.

## 3. Architecture

`server/harness/` grows three additive subpackages. No existing file is
restructured; integration happens via thin import-and-call hooks at
well-defined seams.

```
server/harness/
├── (existing) config, ledger, tuning, routing_compaction,
│              model_assignment, reviews, shadow, replay, meta
├── validate.py         ← Phase 1: static dry-run for HarnessConfig
├── hooks/              ← Phase 2: pre/post-tool hooks (observe + block)
│   ├── __init__.py     · public API
│   ├── _bundled/       · in-tree hooks, auto-imported at startup
│   └── _project/       · gitignored; site-specific gates
└── skills/             ← Phase 3: member-declared markdown bundles
    ├── __init__.py     · public API: load_skills, list_skills
    ├── loader.py
    └── _library/<skill-name>/SKILL.md
```

Each new subpackage is independently shippable. PR sequencing is in §9.

## 4. Phase 1 — `validate.py` (static dry-run)

**Goal.** Catch broken `HarnessConfig` before `apply_harness_review` writes
it. Zero LLM calls, runs in milliseconds, surfaces typos and structurally
broken configs.

### 4.1 Public API

```python
def validate_config(
    candidate: HarnessConfig | dict,
) -> ValidationReport
```

`ValidationReport` is a frozen dataclass:

| Field | Type | Meaning |
|---|---|---|
| `ok` | `bool` | shortcut for `readiness == "ready"` |
| `errors` | `list[ValidationIssue]` | block apply |
| `warnings` | `list[ValidationIssue]` | proceed but flag |
| `readiness` | `Literal["ready", "warning", "blocked"]` | summary verdict |

`ValidationIssue`: `code: str`, `path: str` (dotted config path), `message: str`,
`severity: Literal["error", "warning"]`.

### 4.2 Checks

**Schema.** Dataclass-driven (type/range/required). Largely free from the
existing `HarnessConfig` definition; validator just exercises it.

**Cross-reference.** All must resolve against the live project state:

| Check | Source of truth |
|---|---|
| Models in `per_query_type.*.model_preferences` exist | Allowed set derived from `server/board/config.py` accessors (`get_chairman_model`, `get_council_models`, `get_classifier_model`, `get_verification_model`) plus the live `kimi/…`, `qwen/…`, `glm/…`, `deepseek/…`, `gemini/…`, `openrouter:…` prefix conventions from `server/board/llm.py` |
| Member IDs in `routing.suppressed_member_ids` exist and aren't shelved | `server/members/*.md` (`_`-prefixed files are shelved) |
| `per_query_type` keys match known query types | Classifier output schema (enumerated in `server/board/deliberation/classifier.py`) |
| `compaction.stage1_sections` values are valid | `_VALID_STAGE1_COMPACTION_SECTIONS` in `server/harness/config.py` |
| `hardening.{atomizer_model, contradiction_judge_model, sotb_judge_model, auto_promote_summarizer_model}` resolve | Same allowed set as above; `None` is also valid (falls back to `atomizer_model`) |

**Safety.** Higher-level invariants:

- Suppression doesn't empty the routing pool for any query type (would
  silently break the Board).
- Token budgets within `tuning.py` floors/ceilings.
- `hardening.disagreement_threshold` ∈ [1, 10] (auto-promote sanity).
- `verification_threshold` ∈ [`VERIFICATION_THRESHOLD_FLOOR`, `VERIFICATION_THRESHOLD_CEILING`].

### 4.3 Integration

- `reviews.run_harness_review()` calls `validate_config(snapshot)` on the
  proposed snapshot; result attached to the review JSON as a top-level
  `validation` field.
- `reviews.apply_harness_review()` calls `validate_config(snapshot)` and
  refuses to apply when `readiness == "blocked"`, raising
  `HarnessReviewError("validation blocked: <first error code>")`.
- CLI: `uv run python -m server.cli --harness-validate [path/to/config.json]`
  prints the report and exits non-zero if blocked.
- HTTP API: `POST /harness/validate` with a candidate config body returns
  the `ValidationReport` as JSON.

### 4.4 Failure modes

- Validator crash on a malformed input must never block a review's
  recommendations. Wrap the call in `run_harness_review` so failure becomes
  a `HarnessRecommendation` with category `validation`, summary
  `"validation check failed"`, details `{"error": str(exc)}`.

## 5. Phase 2 — `hooks/` (observe + block)

**Goal.** Gate `web_search` and delegated-task creation through a registered
hook chain. Pre-hooks may deny; pre- and post-hooks log to the ledger.

### 5.1 ABI

```python
@dataclass(frozen=True)
class HookContext:
    tool_name: str          # "web_search" | "delegated_task"
    stage: int              # 1..4 (0 for harness internals)
    session_id: str
    member_id: str | None
    request: dict           # tool inputs (read-only)

@dataclass(frozen=True)
class HookVerdict:
    action: Literal["allow", "deny"]
    reason: str | None      # required when action == "deny"
    metadata: dict          # logged to ledger

PreHook  = Callable[[HookContext], HookVerdict | Awaitable[HookVerdict]]
PostHook = Callable[[HookContext, dict], None | Awaitable[None]]
```

Pre-hooks are pure observers + gate; they may not mutate `request`.
Post-hooks see the result dict but may not mutate it.

### 5.2 Registry

```python
def register_pre_hook(tool_name: str, fn: PreHook) -> None
def register_post_hook(tool_name: str, fn: PostHook) -> None
async def dispatch_pre_hooks(ctx: HookContext) -> HookVerdict
async def dispatch_post_hooks(ctx: HookContext, result: dict) -> None
```

**Dispatch semantics.** Pre-hooks fire in registration order. The first
`deny` short-circuits the chain and is returned. If all return `allow`, the
final verdict is `allow` with merged metadata. Post-hooks all fire (no
short-circuit) and log independently.

**Hook discovery.** At startup the harness imports every Python module in
`server/harness/hooks/_bundled/` and `server/harness/hooks/_project/` (if
present). Hook modules call `register_pre_hook` / `register_post_hook` at
import time. `_project/` is gitignored so site-specific gates don't leak
into the repo.

### 5.3 Gate sites

- `server/execution/web_search.py` — wrap the public entry function (likely
  `web_search(...)`; exact name confirmed at implementation time). On deny,
  raise `HookDeniedError(reason)` for the caller to surface.
- `server/execution/tasks.py` — wrap `plan_delegated_task`,
  `save_delegated_task`, and `update_delegated_task_status`. Each site
  builds a `HookContext` with the available `session_id` and `member_id`.

### 5.4 Bundled hooks (V1)

| Hook | Tool | Default | Behavior |
|---|---|---|---|
| `cap_web_search_per_session` | `web_search` | 20 | Reads count from new `hook_events` table; deny once exceeded |
| `rate_limit_delegated_tasks` | `delegated_task` | 5/min | Sliding window over `hook_events`; deny on burst |

Both bundled hooks are proof-of-concept. Site-specific gates go in
`_project/`.

### 5.5 Failure modes

- A hook that raises is treated as `deny` with reason `"hook crashed: <type>"`;
  the exception traceback is logged via `logging.exception` but does not
  propagate. This prevents a buggy hook from taking down the call site.
- An async hook returning a coroutine that times out: dispatch wraps each
  hook in `asyncio.wait_for(fn(...), timeout=5.0)`; timeout → deny with
  reason `"hook timeout"`.

## 6. Phase 3 — `skills/` (member-declared bundles)

**Goal.** Members opt into named markdown bundles via YAML frontmatter; the
harness loads bundle bodies and appends them to the member's system prompt at
Stage 1 and Stage 2 entry.

### 6.1 Skill file shape

`server/harness/skills/_library/<skill-name>/SKILL.md`:

```markdown
---
name: pricing_research
description: |
  Methods for early-stage SaaS pricing research: van Westendorp,
  Gabor-Granger, willingness-to-pay interviews.
---
When asked about pricing, prefer these methods in order:
1. Van Westendorp Price Sensitivity Meter — when …
[body]
```

The directory wrapper (`<skill-name>/`) leaves room for future attachments
(templates, JSON examples) without breaking the loader API.

### 6.2 Member frontmatter extension

`server/members/strategist.md`:

```yaml
---
id: strategist
title: Chief Strategist
skills: [pricing_research, jtbd_interview]
---
```

If `skills` is absent or empty, the member behaves exactly as today.
The existing `server/board/loader.py` member parser gains a `skills: list[str]`
field on `BoardMember`.

### 6.3 Loader API

```python
@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: Path

def load_skills(names: list[str]) -> list[Skill]
def list_skills() -> list[Skill]   # for CLI / API surface
```

`load_skills` returns the skills in the order requested. Unknown names emit
a `logging.warning` and are recorded in the session JSON (`data/sessions/<id>.json`)
under `skills.missing[member_id] = [skill_names]`. The ledger column
`skills_used` only carries successfully-loaded skills, keeping schema
simple and tuner queries straightforward.

### 6.4 Injection point

`server/board/deliberation/prompts.py` assembles member system prompts at
Stage 1 and Stage 2 entry. The exact helper function is located during
implementation (likely the existing Stage 1 / Stage 2 prompt builders).
Skill bodies are appended after the member's own system prompt, separated
by a `\n\n---\n\n` divider, in the order declared in member frontmatter.

Skill descriptions are not injected — they exist for `list_skills` and for
operator readability. The model sees only the body.

### 6.5 V1 example skills

Two skills ship as proof-of-concept (chosen to demonstrate, not to be
canonical):

- `pricing_research/SKILL.md` — wired to `strategist` and `product`
- `jtbd_interview/SKILL.md` — wired to `researcher`

### 6.6 Failure modes

- Missing skill file → `logging.warning` + recorded in session JSON
  (see §6.3), member proceeds without it.
- Malformed frontmatter → same handling: warn, skip, member proceeds.
- Body exceeds `MAX_SKILL_BODY_CHARS` (default 8000) → warning + truncation
  with `[…truncated…]` marker. Avoids one runaway skill blowing the
  member's prompt budget.

## 7. Cross-cutting: ledger integration

All three subsystems write to the ledger so future tuners can learn from
their behavior. Additions go through `_ensure_columns` in `ledger.py` —
purely additive, no migrations required.

| Subsystem | Change |
|---|---|
| validate | New column `validation_warnings` (JSON list) on `session_outcomes`; per-review validation snapshot inside `harness_config_activations.snapshot` |
| hooks | **New table** `hook_events(session_id TEXT, tool_name TEXT, action TEXT, reason TEXT, metadata TEXT, ts TEXT)` |
| skills | New column `skills_used` (JSON map: `member_id → [skill_names]`) on `session_outcomes`; full per-member list also in `data/sessions/<id>.json` |

The hooks table is the only schema-shaped change beyond a column addition;
it's keyed only by `session_id` (no FK constraint) and is append-only.

## 8. Testing strategy

- **Validate.** Pure unit tests, no LLM calls. Fixture set covers:
  unknown model, suppressed-and-shelved member, empty routing pool after
  suppression, budget below floor, schema-violating shape. Each fixture
  asserts the expected `readiness` and at least one `errors` code.
- **Hooks.** Unit tests with a stub registry verify dispatch order, deny
  short-circuit, exception → deny conversion, and timeout → deny conversion.
  One integration test wraps `web_search` with a denying hook and confirms
  the execution layer surfaces `HookDeniedError` correctly.
- **Skills.** Loader unit tests (well-formed, malformed, missing). One
  integration test mocks the orchestrator and asserts skill body appears in
  the assembled prompt at Stage 1 and Stage 2 with the expected separator.
- **No live LLM tests** unless explicitly approved (mocked LLM is the
  default per project preference).

## 9. PR decomposition

Each PR is independently shippable, reversible, and tested in isolation.

| PR | Scope | Est. LoC (incl. tests) |
|---|---|---|
| 1 | `validate.py` + `reviews.py` integration + CLI/API surface + tests | ~400 |
| 2 | `hooks/` infra + 2 bundled hooks + wrap `web_search` + tests | ~450 |
| 3 | Wrap `tasks.py` call sites + tests | ~200 |
| 4 | `skills/` infra + loader + 2 example skills + member frontmatter extension + tests | ~350 |
| 5 | Skills injection into board prompt assembly at Stage 1 + Stage 2 + tests | ~250 |

PRs 2 and 3 are split because the hook infra is a self-contained landing
zone; wiring it into `tasks.py` benefits from a separate review of just the
call-site wraps. Likewise PRs 4 and 5 separate "skills exist" from "skills
are used by the Board" so the Board change can be reviewed without the new
loader as noise.

## 10. Out of scope (explicitly)

- **MCP transport** — no external tool consumer; defer.
- **Modify-power hooks** — observe + block only.
- **Skill auto-discovery / model-invoked skills** — members declare statically.
- **Per-query-type skill filtering** — member-declared only.
- **UI surfaces** beyond CLI and HTTP API.
- **Replay-based dry-run** — `shadow.py` covers post-apply regression.

## 11. Open questions

- Should the validator be exposed as an `argparse` subcommand
  (`server.cli harness validate`) or kept as a top-level flag
  (`--harness-validate`)? Defer to implementation-time consistency with
  existing CLI shape.
- Which helper inside `server/board/deliberation/prompts.py` is the
  single right injection point for both Stage 1 and Stage 2? Located by
  inspection during Phase 3 implementation; if Stages 1 and 2 don't share
  one helper, inject at both call sites with the same divider.
- Should `_project/` hooks be loaded only when an env flag opts in
  (e.g., `AGENTIC_BOARD_HOOKS_PROJECT=1`)? Defer; default to "load if
  present" with a startup log line listing what was loaded.
