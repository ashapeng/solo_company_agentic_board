# Milestone Pipeline: Agent Team Architecture Deep Dive

> **Purpose**: Onboard new team members and instruct coding agents on the design, communication patterns, data fidelity mechanisms, and anti-hallucination strategies of the milestone generation pipeline.
>
> **Last updated**: 2026-02-24

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Directory Map](#2-directory-map)
3. [Execution Flow — The 7-Step Pipeline](#3-execution-flow--the-7-step-pipeline)
4. [Shared State: The Central Ledger](#4-shared-state-the-central-ledger)
5. [Base Agent Contract](#5-base-agent-contract)
6. [Agent-by-Agent Specification](#6-agent-by-agent-specification)
   - [Agent 1: SpecInterpreterAgent](#agent-1-specinterpreteragent)
   - [Agent 2: SpecClarityAgent](#agent-2-specclarityagent)
   - [Agent 3: RoleAgent](#agent-3-roleagent)
   - [Agent 4: RoleCriticAgent](#agent-4-rolecriticagent)
   - [Agent 5: MilestonePlannerAgent](#agent-5-milestoneplanneragent)
   - [Agent 6: MilestoneReviewerAgent](#agent-6-milestonerevieweragent)
   - [Standalone Agents](#standalone-agents)
7. [Inter-Agent Communication Model](#7-inter-agent-communication-model)
8. [Information Fidelity — How Data Is Faithfully Preserved](#8-information-fidelity--how-data-is-faithfully-preserved)
9. [Anti-Hallucination Strategy](#9-anti-hallucination-strategy)
10. [The Assembler — Final Plan Construction](#10-the-assembler--final-plan-construction)
11. [Dual Execution Paths: Orchestrator vs Streaming](#11-dual-execution-paths-orchestrator-vs-streaming)
12. [LLM Infrastructure Layer](#12-llm-infrastructure-layer)
13. [Persistence and Resume](#13-persistence-and-resume)
14. [Known Limitations and Technical Debt](#14-known-limitations-and-technical-debt)
15. [Essential Files Quick Reference](#15-essential-files-quick-reference)

---

## 1. System Overview

The **Milestone Pipeline** is a sequential multi-agent system that transforms a project specification into a structured project plan with milestones, roles, evaluation rubrics, and acceptance criteria.

### What It Produces

Given a project spec (title, description, objectives, deliverables, timeline), the pipeline generates:

- **Spec Understanding** — factual extraction of what the project actually says
- **Clarity Assessment** — gate decision: is the spec clear enough to plan?
- **Roles** — 2-5 suitable roles with seniority levels and skills
- **Milestones** — N sequential milestones, each with days allocation, deliverables, acceptance criteria, and weighted evaluation rubrics
- **Final Plan** — assembled, cross-validated output combining all of the above

### Architecture Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│                        PipelineService                          │
│   (HTTP adapter: idempotency, BOLA, PAYG threading, resume)    │
└──────────────────────────┬──────────────────────────────────────┘
                           │
              ┌────────────▼────────────┐
              │   PipelineOrchestrator   │
              │  (sequential 7-step      │
              │   coordination with      │
              │   checkpoint + retry)    │
              └────────────┬────────────┘
                           │
      ┌────────┬───────────┼───────────┬────────┬────────┐
      ▼        ▼           ▼           ▼        ▼        ▼
   Agent 1  Agent 2    Agent 3    Agent 4   Agent 5  Agent 6
   (Spec    (Clarity   (Role      (Role     (Milestone (Milestone
   Interp)  Gate)      ID)        Critic)   Planner)   Reviewer)
      │        │           │           │        │        │
      └────────┴───────────┴───────────┴────────┴────────┘
                           │
              ┌────────────▼────────────┐
              │        Assembler         │
              │  (pure Python merge +    │
              │   cross-validation)      │
              └────────────┬────────────┘
                           │
                           ▼
                      final_plan
```

**This is NOT a graph or DAG.** It is a strict **sequential pipeline** — each agent runs after the previous one completes. There are no parallel branches, no fan-out, no conditional routing (except the clarity gate which halts the pipeline).

### Design Philosophy

The pipeline follows the **Generator → Critic** pattern (sometimes called "Producer → Verifier"):

| Phase | Agent Pair | Pattern |
|-------|-----------|---------|
| Roles | RoleAgent → RoleCriticAgent | Generate then refine |
| Milestones | MilestonePlannerAgent → MilestoneReviewerAgent | Generate then verify+fix |

Critics receive the generator's output and correct it against hard constraints. The orchestrator may loop the milestone critic up to 2 times if constraint violations persist.

#### Hot Generator / Cold Critic Temperature Pattern

The generator-critic pairs use a deliberate **temperature asymmetry**:

| Agent | Role | Temperature | Rationale |
|-------|------|------------|-----------|
| RoleAgent | Generator | 0.2 | Constrained identification — limited creativity needed |
| RoleCriticAgent | Critic | **0.1** | Colder than generator for deterministic, systematic critique |
| MilestonePlannerAgent | Generator | **0.5** | Warm — with thinking enabled, explores diverse decompositions then converges |
| MilestoneReviewerAgent | Critic | **0.1** | Strictly colder than planner — deterministic constraint enforcement |

The warm planner temperature (0.5) is intentional: with thinking mode enabled on reasoning models, the LLM explores multiple milestone decomposition strategies during the reasoning phase, then selects the best option. The arithmetic constraints (days sum, rubric weights) are enforced downstream by the cold reviewer (0.1), so the planner is free to explore. This "hot/cold" pairing prevents both the homogeneity of always-cold generation and the inconsistency of always-warm critique.

---

## 2. Directory Map

```
backend/app/agents/autonomous/milestone_pipeline/
├── __init__.py                # Public API exports
├── state.py                   # PipelineState — shared mutable context + audit trail
├── base.py                    # BasePipelineAgent — LLM calls, JSON parsing, retry
├── orchestrator.py            # PipelineOrchestrator — 7-step sequential coordination
├── streaming_runner.py        # StreamingPipelineRunner — SSE event stream (stateless)
├── assembler.py               # Assembler — merges outputs + cross-validation
├── validators.py              # Shared validation: constraint checks for orchestrator + streaming
├── prompt_loader.py           # PromptLoader — .md file I/O with in-memory cache
└── agents/
    ├── __init__.py            # Exports all agents
    ├── spec_interpreter.py    # Agent 1: factual spec extraction
    ├── spec_clarity.py        # Agent 2: gate decision (stop or continue)
    ├── role_agent.py          # Agent 3: identify 2-5 roles
    ├── role_critic.py         # Agent 4: refine roles, apply corrections
    ├── milestone_planner.py   # Agent 5: generate N milestones with rubrics
    ├── milestone_reviewer.py  # Agent 6: verify constraints, auto-fix violations
    ├── outcomes_clarity.py    # Standalone: outcomes gate for wizard step 2
    ├── milestone_count.py     # Standalone: suggest milestone count
    ├── criteria_regeneration.py # Standalone: regenerate success criteria
    ├── executive_summary.py   # Standalone: marketplace summary
    ├── description_polisher.py # Standalone: polish description text
    └── outcomes_polisher.py   # Standalone: polish outcomes text

backend/app/agents/prompts/milestone_pipeline/
├── spec_interpreter_prompt.md
├── spec_clarity_prompt.md
├── role_agent_prompt.md
├── role_critic_prompt.md
├── milestone_planner_prompt.md
├── milestone_reviewer_prompt.md
├── outcomes_clarity_prompt.md
├── executive_summary_prompt.md
├── milestone_count_prompt.md
├── criteria_regeneration_prompt.md
├── description_polish_prompt.md
└── outcomes_polish_prompt.md

backend/app/schemas/milestone_pipeline/
├── input_schemas.py           # ProjectSpec — the primary input type
├── spec_schemas.py            # SpecUnderstanding, CompanyQuestions, SpecClarity
├── role_schemas.py            # Role, IdentifiedRoles
├── critic_schemas.py          # RefinedRolesSchema, RefinedMilestonesSchema
├── milestone_schemas.py       # Milestone, EvaluationRubricItem, MilestonesSchema
└── clarification_schemas.py   # Per-wizard-step schemas (polishers, suggestions, etc.)
```

**Supporting infrastructure:**

```
backend/app/agents/
├── llm_provider.py            # Multi-provider registry + unified streaming API
├── llm_orchestrator.py        # Model selection by tier, strategy, task type
├── llm_strategies.py          # Strategy config tables
└── task_context.py            # TaskContext, TaskType, REASONING_TASK_TYPES

backend/app/services/
└── milestone_pipeline_service.py  # HTTP adapter: idempotency, resume, BOLA

backend/app/repositories/
└── pipeline_state_repository.py   # Supabase CRUD for pipeline_states table
```

---

## 3. Execution Flow — The 7-Step Pipeline

```
PipelineOrchestrator.run(project_spec, initial_state?, user_clarifications?, project_id, user_id)
│
├── A. STATE INITIALIZATION
│   ├── Fresh run: PipelineState(state_id=uuid4(), project_spec=spec, status="in_progress")
│   └── Resume: PipelineState.from_dict(initial_state)
│
├── B. RESUME WITH CLARIFICATIONS (if user_clarifications provided)
│   ├── Merge clarification text into project_spec["project_description"]
│   ├── Re-run SpecInterpreterAgent with previous_understanding
│   ├── state.spec_understanding = result.model_dump()
│   └── state.pipeline_stage = "CLEAR_TO_CONTINUE" (skip clarity gate)
│
├── C. INITIAL RUN (pipeline_stage == "INITIAL")
│   │
│   ├── Step 1: SpecInterpreterAgent
│   │   → state.spec_understanding = result.model_dump()
│   │   → checkpoint("SPEC_INTERPRETED")
│   │
│   ├── Step 2: SpecClarityAgent
│   │   → state.spec_clarity = clarity.model_dump()
│   │   └── IF not ready_for_planning:
│   │       → state.pipeline_stage = "STOPPED_AFTER_CLARITY"
│   │       → state.status = "stopped_for_clarification"
│   │       → RETURN state.to_dict()  ◄── PIPELINE HALTS
│   │
│   └── state.pipeline_stage = "CLEAR_TO_CONTINUE"
│
├── D. CONTINUATION (pipeline_stage == "CLEAR_TO_CONTINUE")
│   │
│   ├── Step 3: RoleAgent
│   │   → validate: at least 1 role
│   │   → state.identified_roles = roles.model_dump()
│   │
│   ├── Step 4: RoleCriticAgent
│   │   → state.role_critique = refined_roles.model_dump()
│   │   → checkpoint("ROLES_REFINED")
│   │
│   ├── Step 5: MilestonePlannerAgent
│   │   → IN: project_spec + refined_roles + spec_understanding
│   │   → validate: at least 1 milestone
│   │   → state.milestones = milestones.model_dump()
│   │
│   ├── Step 6: MilestoneReviewerAgent [LOOP up to 2 iterations]
│   │   │ FOR iteration in range(MAX_CRITIC_ITERATIONS=2):
│   │   │   → refined = MilestoneReviewerAgent.run(milestones, spec, roles, spec_understanding)
│   │   │   → violations = check_milestone_constraints(refined, spec)
│   │   │   → IF no violations: BREAK
│   │   │   → IF not last iteration: milestones = MilestonesSchema(refined.milestones)
│   │   │                            (strip corrections, re-enter loop)
│   │   → state.milestone_critique = refined.model_dump()
│   │   → checkpoint("MILESTONES_REVIEWED")
│   │
│   └── Step 7: Assembler.assemble_final_plan()
│       → state.final_plan = final_plan
│       → state.status = "completed"
│       → state.pipeline_stage = "COMPLETED"
│       → RETURN final_plan
```

### Error Handling

Every step is wrapped in `try/except`. On failure:

```python
try:
    result = await self._timed_run("Step N", agent.run(...))
except Exception as e:
    self._record_stage_failure("STEP_NAME", e)  # appends to failed_steps, increments retry_count
    raise  # propagates to PipelineService → HTTP 500
```

---

## 4. Shared State: The Central Ledger

`PipelineState` (`state.py`) is a Pydantic `BaseModel` that acts as the **single source of truth** for the entire pipeline run. It is NOT passed directly between agents — the orchestrator reads from it and writes to it after each agent completes.

### State Fields

| Field | Type | Written By | Read By |
|-------|------|-----------|---------|
| `state_id` | `UUID` | Init | DB operations, resume |
| `project_id` | `UUID?` | Init | Idempotency check |
| `user_id` | `UUID?` | Init | BOLA check on resume |
| `pipeline_stage` | `str` | Orchestrator | Resume routing, checkpoint |
| `status` | `str` | Orchestrator | Service layer response shaping |
| `user_tier` | `str?` | Init | Persisted across pause/resume |
| `pipeline_strategy` | `str?` | Init | LLM model selection |
| `is_pay_as_you_go` | `bool` | Init | LLM tier bumping |
| `project_spec` | `Dict?` | Init | All agents (via orchestrator) |
| `spec_understanding` | `Dict?` | After Step 1 | Steps 2, 3, 5, 6, Resume |
| `spec_clarity` | `Dict?` | After Step 2 | Service layer (questions) |
| `identified_roles` | `Dict?` | After Step 3 | Step 4 |
| `role_critique` | `Dict?` | After Step 4 | Steps 5, 6, Assembler |
| `milestones` | `Dict?` | After Step 5 | Step 6 |
| `milestone_critique` | `Dict?` | After Step 6 | Assembler |
| `final_plan` | `Dict?` | After Step 7 | Service layer (response) |
| `audit_log` | `Dict` | Every update | Debugging, traceability |
| `failed_steps` | `List[str]` | On error | Debugging |
| `retry_count` | `int` | On error | Debugging |

### Stage Progression

```
INITIAL → SPEC_INTERPRETED → CLEAR_TO_CONTINUE → ROLES_REFINED → MILESTONES_REVIEWED → COMPLETED
                                  ↑
                    STOPPED_AFTER_CLARITY (pause/resume branch)
```

### Key Design Decision: Hybrid Type Strategy (Typed Handoffs, Dict Persistence)

The pipeline uses a **two-layer type system**. This is often misunderstood as "dicts, not typed models" — but the reality is more nuanced.

**Layer 1 — Agent-to-agent handoffs are TYPED (on fresh runs).**
The orchestrator keeps local typed variables and passes them directly between steps:

```python
_typed_understanding = await self.spec_interpreter.run(project_spec)          # → SpecUnderstanding
clarity = await self.spec_clarity.run(project_spec, _typed_understanding)     # receives SpecUnderstanding
roles = await self.role_agent.run(role_context, _typed_understanding)         # receives SpecUnderstanding
refined_roles = await self.role_critic.run(roles, project_spec)              # receives IdentifiedRoles
milestones = await self.milestone_planner.run(project_spec, refined_roles, understanding)   # + spec_understanding
refined_ms = await self.milestone_reviewer.run(milestones, spec, refined_roles, understanding) # + spec_understanding
```

**Layer 2 — State persistence stores DICTS.**
After each step, the orchestrator writes `.model_dump()` to state for DB serialization:

```python
self.state.update("spec_understanding", _typed_understanding.model_dump())  # Dict stored
self.state.update("identified_roles", roles.model_dump())                   # Dict stored
```

**Serialization and reconstruction:**
- `PipelineState.to_dict()` calls `model_dump(mode='json')` — pre-serialized dicts avoid nested model serialization complexity
- `PipelineState.from_dict(data)` reconstructs typed Pydantic models from raw DB dicts using a `_TYPED_FIELDS` registry (see below)
- Forward-compatible: if `SpecUnderstanding` adds a field in v2, old DB states still deserialize (unknown fields are ignored by `model_validate`)

**`_TYPED_FIELDS` ClassVar pattern** (resolved bug — CLAUDE.md Gotcha #46):
```python
# ClassVar is REQUIRED so Pydantic ignores this as a model field.
# Without ClassVar, Pydantic v2 treats _LOOKUP as ModelPrivateAttr — .items() fails.
_TYPED_FIELDS: ClassVar[Dict[str, type]] = {
    "spec_understanding": SpecUnderstanding,
    "spec_clarity": SpecClarity,
    "identified_roles": IdentifiedRoles,
    "role_critique": RefinedRolesSchema,
    "milestones": MilestonesSchema,
    "milestone_critique": RefinedMilestonesSchema,
}
```

`from_dict()` iterates this mapping and calls `model_cls.model_validate(raw_dict)` for each field that contains a raw dict. If validation fails (e.g., schema evolution removed a field), it falls back to `None` with a warning — defensive against DB states from older code versions.

**Where dicts surface — only in `build_prompts()` static method:**

The `MilestonePlannerAgent.build_prompts()` static method is shared between the orchestrator path (which passes typed models) and the streaming path (which may pass dicts). It uses the duck-typing pattern:

```python
roles_data = roles.model_dump() if hasattr(roles, "model_dump") else roles
```

All other agent `run()` methods accept typed-only parameters — no `Union[Model, Dict]`. The orchestrator always provides typed models on fresh runs, and `from_dict()` reconstructs them on resume.

**Summary of the type strategy:**

| Concern | Fresh Run | Resume from DB |
|---------|-----------|----------------|
| Type safety at handoff | Full (Pydantic models) | Full (reconstructed via `from_dict()`) |
| IDE autocomplete | Yes | Yes (typed fields on PipelineState) |
| Pydantic validation | Automatic at agent output | Re-validated during `from_dict()` reconstruction |
| DB serialization | N/A (typed in memory) | `model_dump(mode='json')` → `model_validate()` round-trip |
| Schema evolution | N/A | Forward-compatible (unknown fields ignored, missing fields → None fallback) |

### Audit Trail

Every `state.update(key, value)` call logs to `audit_log`:

```python
audit_log["spec_understanding"] = {
    "updated_at": "2026-02-22T10:30:45.123456+00:00",
    "value_summary": "object"  # non-primitive types log as "object"
}

# Strings are truncated at 100 chars; primitives (int, float, bool, None) log their str() value
```

This creates a timestamped breadcrumb trail for debugging pipeline runs without needing to inspect the full state blob.

---

## 5. Base Agent Contract

`BasePipelineAgent` (`base.py`) is the parent class of all 12 agents. It provides the complete LLM interaction infrastructure.

### Constructor

```python
BasePipelineAgent(
    temperature=0.7,        # LLM generation temperature (most agents override to 0.1-0.5)
    max_tokens=2000,        # Token budget for LLM response (answer-only for Qwen;
                            #   combined thinking+answer for Kimi/ZhipuAI when thinking enabled)
    task_type=None,         # TaskType literal → drives model selection
    user_tier=None,         # Subscription tier
    pipeline_strategy=None, # A1/A2/A3/B override
    is_pay_as_you_go=False, # PAYG flag → bumps model tier
    thinking_budget=None    # Token budget for thinking phase (see provider-specific semantics below)
)
```

#### `thinking_budget` — Provider-Specific Semantics (CLAUDE.md Gotcha #48)

| Provider | `max_tokens` Meaning | `thinking_budget` Effect |
|----------|---------------------|------------------------|
| **Qwen** | Answer tokens only | Separate `thinking_budget` param controls reasoning tokens |
| **Kimi/ZhipuAI** | Shared between thinking + answer | `max_tokens` is inflated by adding `thinking_budget` at the router level |
| **DeepSeek** | Standard (reasoner always thinks) | Ignored — no budget control |

The `_call_model_by_name()` router in `llm_provider.py` handles this translation transparently. Agents set `max_tokens` based on answer-only estimates and `thinking_budget` separately; the router inflates for providers without separate budgets.

Current thinking budgets: RoleCriticAgent=2048, MilestonePlannerAgent=4096, MilestoneReviewerAgent=4096.

### LLM Call Chain

```
agent.call(system_prompt, user_prompt, response_model)
│
├── agent._call_llm_with_json(system_prompt, user_prompt)
│   ├── LLMOrchestrator.select_model(TaskContext(...))    # if task_type is set
│   ├── requires_reasoning = task_type in REASONING_TASK_TYPES
│   ├── enable_thinking = True if requires_reasoning else None
│   ├── LLMProvider.call(
│   │       system_prompt, user_prompt,
│   │       model_name=selected_model,
│   │       temperature=self.temperature,
│   │       max_tokens=self.max_tokens,
│   │       enable_thinking=enable_thinking,              # activates thinking for reasoning tasks
│   │       thinking_budget=self.thinking_budget          # provider-specific budget
│   │   )                                                 # NOTE: NO response_format="json_object"
│   └── agent._extract_json_from_text(raw_response)       # strips markdown fences, finds JSON
│
└── agent._parse_structured_output(json_string, response_model)
    ├── json.loads(json_string)
    ├── Single-key dict unwrapping (if needed)
    └── response_model(**parsed_dict)                      # Pydantic validation
```

#### Why No `response_format="json_object"` (CLAUDE.md Gotcha #47)

**`response_format="json_object"` is intentionally NOT used.** It is incompatible with thinking mode on Qwen, Kimi, and ZhipuAI:

| Provider | Failure Mode with `json_object` + Thinking |
|----------|-------------------------------------------|
| **Qwen** | Puts JSON in `reasoning_content` instead of `content` |
| **Kimi** | Returns API errors |
| **ZhipuAI** | Produces invalid output |

Since thinking mode is the core capability of reasoning models (and the pipeline's primary quality driver for Pro/Business tiers), the pipeline **always chooses thinking over json_object**. JSON structure is enforced through three alternative layers:

1. **Prompt instructions** — "Respond with valid JSON only" in every agent prompt
2. **`_extract_json_from_text()` fallback** — strips markdown fences, scans for `{...}` boundaries
3. **`call_with_retry()`** — retries once on `StructuredOutputError` (transient parse failures)

### JSON Extraction: 3-Level Fallback

LLMs sometimes wrap JSON in markdown code fences or include preamble text. `_extract_json_from_text` handles this:

1. **Strip fences** — Removes `` ```json ... ``` `` wrappers
2. **Direct parse** — `json.loads(text)` on the cleaned text
3. **Bounding braces** — Scans for first `{` and last `}`, extracts that substring, parses it

### Retry Mechanism

```python
call_with_retry(system_prompt, user_prompt, response_model, max_retries=2)
```

| Error Type | Retry Behavior |
|-----------|---------------|
| `LLMProviderError` / `TimeoutError` | Up to 3 attempts with exponential backoff + jitter |
| `StructuredOutputError` (bad JSON/schema) | 1 retry only, 1 second pause |
| All retries exhausted | Re-raises the last error |

**Backoff formula:**
```
base = min(AGENT_RETRY_BACKOFF_BASE * 2^attempt, AGENT_RETRY_BACKOFF_MAX)
actual = base + random(0, 0.25 * base)
```

### Helper Methods

```python
BasePipelineAgent.to_json(data)      # json.dumps with UUID/datetime serializer
self.format_input(label, data)       # Returns "Label:\n{json_data}"
```

---

## 6. Agent-by-Agent Specification

### Model Selection Is Tier-Dependent

Each agent's property table includes a **Reasoning-Eligible** row. This indicates whether the agent's `task_type` is in `REASONING_TASK_TYPES` (defined in `task_context.py`). When eligible, `enable_thinking=True` is sent to the LLM — but the actual **model** selected depends on the user's subscription tier and cost-class filtering in `llm_strategies.py`:

| Tier | Non-Reasoning Tasks | Reasoning-Eligible Tasks |
|------|--------------------| -------------------------|
| **Launch** | Economy only (`qwen-flash`, `deepseek-chat`, `kimi-k2`) | Same economy models — `enable_thinking=True` sent but limited by model capability |
| **Pro** | Standard only (`qwen-plus`, `kimi-k2.5`) | Reasoning models on-demand (`qwen3-max`, `deepseek-reasoner`) + `enable_thinking=True` |
| **Business** | Reasoning + Standard (reasoning preferred) | Reasoning models always (`qwen3-max`, `deepseek-reasoner`) + `enable_thinking=True` |

**Key insight:** A Launch-tier user running the milestone planner (reasoning-eligible) gets `qwen-flash` with `enable_thinking=True` — the model can do basic hybrid thinking but lacks the depth of a dedicated reasoning model like `qwen3-max`. A Business-tier user gets `qwen3-max` with full extended thinking. Same agent, same code path, different quality ceiling. The PAYG ($35/project) upgrade bumps Launch→Pro and Pro→Business model selection. See Section 12 and `llm_strategies.py` for the full tier configuration.

---

### Agent 1: SpecInterpreterAgent

> **File:** `agents/spec_interpreter.py`
> **Purpose:** Extract factual information from the project spec — nothing more.

| Property | Value |
|----------|-------|
| Temperature | `0.1` (lowest — pure extraction) |
| Max Tokens | `2000` |
| Task Type | `spec_interpretation` |
| Reasoning-Eligible | No — standard/economy model for all tiers |

#### Input

| Parameter | Source | Description |
|-----------|--------|-------------|
| `project_spec` | Enterprise user input | Full spec dict |
| `previous_understanding` | `state.spec_understanding` (resume only) | Prior extraction for consolidation |

#### Output Schema: `SpecUnderstanding`

```json
{
  "generated_title": "Concise Project Title (max 10 words)",
  "interpreted_summary": "Factual summary of the project spec",
  "extracted_objectives": ["Objective 1", "Objective 2", "..."],
  "assumptions": ["Assumption: X implies Y", "..."],
  "unclear_elements": ["Unclear: timeline not specified", "..."]
}
```

#### State Written

```python
state.update("spec_understanding", result.model_dump())
```

#### Special Behaviors

**Title override:** If the user provided a project name (not "Untitled Project"), the agent:
1. Adds a hard instruction to the system prompt: `"Use the provided project_name '...' as the generated_title."`
2. After the LLM call, forces the title regardless: `result.model_copy(update={"generated_title": user_title})`

This double-enforcement ensures the user's chosen title is never overwritten by the LLM.

#### Anti-Hallucination Rules

- "Extract ONLY information explicitly stated"
- "DO NOT invent features, requirements, or capabilities not mentioned"
- "If unclear, mark in `unclear_elements` — do not fill gaps with assumptions"
- Any inference MUST be prefixed with "Assumption: X implies Y"

---

### Agent 2: SpecClarityAgent

> **File:** `agents/spec_clarity.py`
> **Purpose:** Gate decision — is the spec clear enough to proceed, or should we ask questions?

| Property | Value |
|----------|-------|
| Temperature | `0.2` |
| Max Tokens | `2000` |
| Task Type | `spec_clarity` |
| Reasoning-Eligible | No — standard/economy model for all tiers |

#### Input

| Parameter | Source | Description |
|-----------|--------|-------------|
| `project_spec` | Enterprise user input | Full spec dict |
| `spec_understanding` | Agent 1 output | Factual extraction (typed or dict) |

When `spec_understanding` is provided, the agent receives a combined context:
```python
context = {
    "project_spec": project_spec,
    "spec_understanding": understanding_data
}
```

#### Output Schema: `SpecClarity`

```json
{
  "questions_for_company": {
    "project_scope": ["What is the primary deliverable?"],
    "technical_requirements": ["Any existing systems to integrate?"],
    "data_requirements": [],
    "evaluation_expectations": []
  },
  "ready_for_planning": false,
  "mode": "clarification_needed"
}
```

#### Gate Decision Rules

**Set `ready_for_planning = FALSE` if ANY:**
- Description < 20 words
- No extractable objectives
- Critical technical details missing AND cannot be inferred
- Contradictory requirements
- Impossible timeline

**Set `ready_for_planning = TRUE` if ALL:**
- Description >= 20 words with actionable detail
- At least 1 identifiable objective
- Deliverables can be inferred
- No major contradictions

**Tie-breaker:** "When in doubt, proceed (`ready_for_planning = true`)."

#### Pipeline Gate Effect

```python
if not clarity.ready_for_planning:
    state.pipeline_stage = "STOPPED_AFTER_CLARITY"
    state.status = "stopped_for_clarification"
    return state.to_dict()  # ← PIPELINE HALTS HERE
```

The service layer saves state to the database and returns `PipelineClarityQuestionsResponse` to the API. The user answers the questions, and the pipeline resumes via the clarification flow.

#### Question Count Rules (Strict)

| Count | When |
|-------|------|
| 2 | Moderate detail, 1-2 key pieces missing |
| 3 | Somewhat vague spec |
| 4 | Quite sparse spec |
| 5 | Extremely vague (hard maximum — never exceed 5) |

#### Anti-Duplication Rule

If `spec_understanding` is provided, the agent MUST NOT re-ask about objectives or information already extracted — only ask about `unclear_elements`.

---

### Agent 3: RoleAgent

> **File:** `agents/role_agent.py`
> **Purpose:** Identify 2-5 suitable roles for the project.

| Property | Value |
|----------|-------|
| Temperature | `0.2` |
| Max Tokens | `2000` |
| Task Type | `role_identification` |
| Reasoning-Eligible | No — standard/economy model for all tiers |

#### Input

| Parameter | Source | Description |
|-----------|--------|-------------|
| `project_spec` | Orchestrator-trimmed | Only role-relevant fields (see below) |
| `summary` | Agent 1 output | SpecUnderstanding (typed or dict) |

**Context trimming** (done by the orchestrator, not the agent):
```python
role_context = {
    "project_name": spec.get("project_name"),
    "project_description": spec.get("project_description"),
    "objectives": spec.get("objectives"),
    "outcome_per_deliverable": spec.get("outcome_per_deliverable"),
}
if spec.get("project_goals"):
    role_context["project_goals"] = spec["project_goals"]
```

This is a deliberate information scoping technique — the role agent doesn't see timeline, milestone count, or other irrelevant fields. The optional `project_goals` field (e.g., "hiring", "bounty", "marketing") conditions how roles are shaped — hiring goals emphasize demonstrable skills, bounty goals emphasize solution-oriented expertise, marketing goals emphasize content creation ability.

#### Output Schema: `IdentifiedRoles`

```json
{
  "identified_roles": [
    {
      "role": "Full Stack Developer",
      "seniority": "mid",
      "core_skills": ["javascript", "react", "nodejs", "api_design"]
    }
  ],
  "skills_tags": ["javascript", "react", "nodejs", "api_design"]
}
```

#### Pydantic Constraints

- `Role.seniority`: `Literal["junior", "mid", "senior", "not_specified"]`
- `Role.core_skills`: `List[str]` — must be `lowercase_underscore` format
- `IdentifiedRoles.identified_roles`: `List[Role]` — required, non-empty

#### Post-Call Validation

```python
self._validate_roles_output(roles)  # Raises PipelineAgentError if len(roles) == 0
```

---

### Agent 4: RoleCriticAgent

> **File:** `agents/role_critic.py`
> **Purpose:** Refine roles — fix names, seniority, skills format, and alignment.

| Property | Value |
|----------|-------|
| Temperature | `0.1` (cold critic — must be colder than RoleAgent's 0.2) |
| Max Tokens | `2500` |
| Thinking Budget | `2048` tokens |
| Task Type | `role_critique` |
| Reasoning-Eligible | **Yes** — `enable_thinking=True`; reasoning model for Pro (on-demand) and Business tiers; economy model for Launch |

#### Input

| Parameter | Source | Description |
|-----------|--------|-------------|
| `roles` | Agent 3 output | IdentifiedRoles (typed or dict) |
| `project_spec` | Orchestrator-trimmed | name, description[:500], objectives |

#### What It Corrects (Auto-Fix, Not Just Flags)

1. Vague role names → specific (e.g., "Support" → "Technical Support Engineer")
2. Seniority mismatches with project complexity
3. Skills count enforcement (2-5 per role)
4. Skills format normalization (`lowercase_underscore`)
5. Role count enforcement (2-5 total, merge duplicates)
6. `skills_tags` deduplication and normalization
7. Role-project alignment — removes roles not justified by the project spec

#### Output Schema: `RefinedRolesSchema`

```json
{
  "identified_roles": [
    {
      "role": "Full Stack Developer",
      "seniority": "mid",
      "core_skills": ["javascript", "react", "nodejs"]
    }
  ],
  "skills_tags": ["javascript", "react", "nodejs"],
  "corrections_applied": [
    "Renamed 'Developer' to 'Full Stack Developer' for specificity",
    "Normalized skill 'API Design' to 'api_design'"
  ]
}
```

The `corrections_applied` field is unique to critic agents — it creates an audit trail of what changed and why.

---

### Agent 5: MilestonePlannerAgent

> **File:** `agents/milestone_planner.py`
> **Purpose:** Generate exactly N milestones with days, deliverables, criteria, and rubrics.

| Property | Value |
|----------|-------|
| Temperature | `0.5` (warm generator — explores diverse decompositions with thinking, reviewer enforces constraints) |
| Max Tokens | `4000` (larger — N milestones each with rubric) |
| Thinking Budget | `4096` tokens |
| Task Type | `milestone_planning` |
| Reasoning-Eligible | **Yes** — `enable_thinking=True`; reasoning model for Pro (on-demand) and Business tiers; economy model for Launch |

**Temperature rationale:** The planner uses the highest temperature in the pipeline (0.5) because with thinking enabled, the model explores multiple decomposition strategies during the reasoning phase and converges on the best option. The MilestoneReviewer (0.1) then enforces all arithmetic constraints, so the planner is free to optimize for creative problem decomposition rather than numeric precision. This is the "hot generator / cold critic" pattern (see Section 1).

#### Input

| Parameter | Source | Description |
|-----------|--------|-------------|
| `project_spec` | Full spec | Includes `milestones` count and `time_needed_days` |
| `roles` | Agent 4 output | RefinedRolesSchema (typed or dict) |
| `spec_understanding` | Agent 1 output (via orchestrator) | Refined interpretation with `interpreted_summary` and `extracted_objectives` — used as canonical source of truth alongside raw spec |

#### Prompt Injection Pattern

Two placeholders are string-replaced before the LLM call:
```python
system_prompt = system_prompt.replace("{milestones_count}", str(spec.get("milestones", 4)))
system_prompt = system_prompt.replace("{time_needed_days}", str(spec.get("time_needed_days", 50)))
```

This embeds the hard numeric constraints directly into the prompt.

#### Output Schema: `MilestonesSchema`

```json
{
  "milestones": [
    {
      "milestone_id": 1,
      "title": "Data Pipeline Foundation",
      "days_allocated": 12,
      "brief_description": "Build the ETL pipeline for data ingestion...",
      "acceptance_criteria": [
        "Pipeline processes 1000+ records without errors",
        "All data transformations pass unit tests"
      ],
      "deliverables": [
        "ERD diagram (PNG or Mermaid)",
        "SQL migration files",
        "ETL pipeline module with tests"
      ],
      "evaluation_rubric": [
        {"criterion": "Code quality", "weight": 30, "scoring_method": "scale_1_5"},
        {"criterion": "Functional requirements met", "weight": 40, "scoring_method": "binary"},
        {"criterion": "Test coverage", "weight": 30, "scoring_method": "scale_1_5"}
      ]
    }
  ]
}
```

#### Pydantic Constraints

| Field | Constraint |
|-------|-----------|
| `Milestone.days_allocated` | `Field(..., ge=1)` — minimum 1 day |
| `Milestone.acceptance_criteria` | `Field(..., min_length=1)` — at least 1 criterion |
| `Milestone.evaluation_rubric` | `Field(..., min_length=1)` — at least 1 rubric item |
| `EvaluationRubricItem.weight` | `Field(..., ge=0, le=100)` |
| `EvaluationRubricItem.scoring_method` | `Literal["binary", "scale_1_5"]` |

#### Hard Constraints (Enforced in Prompt)

1. **EXACTLY** `{milestones_count}` milestones
2. `SUM(days_allocated) == {time_needed_days}` (mathematically verified by LLM before output)
3. Each rubric: `SUM(weights) == 100`
4. Deliverables must be specific artifacts ("ERD diagram", not "documentation")
5. Acceptance criteria must be measurable — blocklisted terms: "good", "proper", "appropriate", "complete", "efficient", "clean", "quality"
6. DO NOT invent milestones for features not in `objectives` or `outcome_per_deliverable`

#### Post-Call Validation (Warning-Only)

```python
if len(result.milestones) != milestones_count:
    logger.warning(f"Expected {milestones_count} milestones, got {len(result.milestones)}")
total_days = sum(m.days_allocated for m in result.milestones)
if total_days != time_needed_days:
    logger.warning(f"Expected {time_needed_days} days, got {total_days}")
```

#### Unique Feature: `build_prompts()` Static Method

```python
@staticmethod
def build_prompts(project_spec, roles, spec_understanding=None) -> Tuple[str, str]:
```

This is shared between the orchestrator path (`run()`) and the streaming path (`StreamingPipelineRunner`), avoiding prompt construction duplication. When `spec_understanding` is provided, it is included in the context dict as a canonical source of truth, giving the LLM access to the refined `interpreted_summary` and `extracted_objectives` from Agent 1.

#### Project Goals Conditioning

When `project_spec` includes a `project_goals` field, the prompt adapts milestone design:

| Goal | Milestone Shaping |
|------|------------------|
| `hiring` | Progressive skill revelation across milestones — early milestones test foundational skills, later ones test advanced capabilities |
| `bounty` | Solution quality focus — milestones emphasize deliverable quality and correctness |
| `marketing` | Reach and engagement metrics — milestones include content creation and distribution tasks |

#### Additional Criteria Propagation

Enterprise users can specify `additional_criteria` in the project spec — custom evaluation criteria that **must** appear in at least one milestone's rubric. These are enterprise-mandated and the planner prompt instructs the LLM to incorporate them rather than ignore them.

---

### Agent 6: MilestoneReviewerAgent

> **File:** `agents/milestone_reviewer.py`
> **Purpose:** Verify milestones against constraints and auto-fix any violations.

| Property | Value |
|----------|-------|
| Temperature | `0.1` (cold critic — strictly colder than MilestonePlanner's 0.5) |
| Max Tokens | `4500` |
| Thinking Budget | `4096` tokens |
| Task Type | `milestone_review` |
| Reasoning-Eligible | **Yes** — `enable_thinking=True`; reasoning model for Pro (on-demand) and Business tiers; economy model for Launch |

#### Input

| Parameter | Source | Description |
|-----------|--------|-------------|
| `milestones` | Agent 5 output (or previous reviewer iteration) | MilestonesSchema (typed) |
| `project_spec` | Orchestrator-trimmed | objectives + description[:1000] |
| `roles` | Agent 4 output | RefinedRolesSchema (typed or dict) |
| `spec_understanding` | Agent 1 output (via orchestrator) | Refined interpretation — used to verify scope alignment with `extracted_objectives` |

Same `{milestones_count}` / `{time_needed_days}` prompt injection as Agent 5.

#### What It Verifies and Auto-Corrects

| Check | Correction |
|-------|-----------|
| Milestone count != N | Add/remove milestones to reach exactly N |
| Days sum != total | Redistribute days proportionally |
| Any milestone days < 1 | Enforce minimum 1 day |
| Vague deliverables | Replace with specific artifacts ("backend code" → "FastAPI routes module") |
| Deliverable count | Usually 1-3, adjusted per complexity |
| Rubric weights != 100 | Fix to sum exactly 100 per milestone |
| Dependency violations | Reorder milestones to respect dependencies |
| Out-of-scope milestones | Remove milestones for features not in spec |
| Vague acceptance criteria | Replace with measurable terms |
| Additional criteria coverage | Verify enterprise `additional_criteria` appear in at least one rubric |
| Project goals alignment | Check milestone progression matches goal type (hiring/bounty/marketing) |
| Scope vs spec_understanding | Verify milestones align with `spec_understanding.extracted_objectives` |

#### Output Schema: `RefinedMilestonesSchema`

```json
{
  "milestones": [...],
  "corrections_applied": [
    "Reordered Milestone 2 and 3 to fix dependency issue",
    "Fixed Milestone 2 rubric weights: 35+35+30=100 (was 40+40+30=110)"
  ]
}
```

#### Orchestrator Retry Loop

```python
MAX_CRITIC_ITERATIONS = 2

for iteration in range(MAX_CRITIC_ITERATIONS):
    refined = await milestone_reviewer.run(milestones, spec, roles, spec_understanding)
    violations = check_milestone_constraints(refined, spec)  # shared validators module
    if not violations:
        break  # Clean pass
    if iteration < MAX_CRITIC_ITERATIONS - 1:
        milestones = MilestonesSchema(milestones=refined.milestones)
        # Strip corrections_applied, feed back for another pass
```

`check_milestone_constraints()` (from `validators.py`) checks:
- Milestone count == expected
- Days sum == expected
- Per-milestone rubric weight sum == 100

---

### Standalone Agents

These agents inherit `BasePipelineAgent` but are NOT part of the main pipeline flow. They serve individual steps of the project creation wizard. All standalone agents use `call_with_retry()` (exponential backoff with jitter, default 2 retries) for resilience against transient LLM failures.

| Agent | Task Type | Temp | Input | Output Schema | Key Behavior |
|-------|-----------|------|-------|---------------|-------------|
| `OutcomesClarityAgent` | `outcomes_clarity` | 0.0 | outcomes list, description | `ClarificationResponse` | Gate agent (deterministic); validates outcome_index bounds |
| `MilestoneCountSuggestionAgent` | `milestone_count` | 0.1 | description, outcomes, deadline | `MilestoneCountSuggestion` | Clamps result to 1-10 |
| `CriteriaRegenerationAgent` | `criteria_regeneration` | 0.1 | milestone_description, project context | `RegenerateCriteriaResponse` | Trims to max 5 criteria |
| `ExecutiveSummaryAgent` | `executive_summary` | 0.4 | description, title, outcomes, deadline, Q&A | `ExecutiveSummaryResponse` | Fallback if description < 10 chars; corrects word_count |
| `DescriptionPolisherAgent` | `description_polish` | 0.3 | description, optional Q&A | `DescriptionPolishResponse` | Light polish or full rewrite |
| `OutcomesPolisherAgent` | `outcomes_polish` | 0.3 | outcomes list, optional Q&A | `OutcomesPolishResponse` | Validates output count matches input; falls back on mismatch |

---

## 7. Inter-Agent Communication Model

Agents in this pipeline **never communicate directly**. All communication is mediated by the orchestrator through the state object.

### Communication Pattern: Orchestrator-Mediated Sequential Handoff

```
                    PipelineOrchestrator
                           │
          ┌────────────────┼────────────────┐
          │                │                │
     reads from       writes to        passes to
     state fields     state fields     next agent
          │                │                │
          ▼                ▼                ▼

Agent 1 ──output──► state.spec_understanding ──input──► Agent 2, Agent 3, Agent 5, Agent 6
Agent 2 ──output──► state.spec_clarity       ──(gate)──► stop or continue
Agent 3 ──output──► state.identified_roles   ──input──► Agent 4
Agent 4 ──output──► state.role_critique      ──input──► Agent 5, Agent 6
Agent 5 ──output──► state.milestones         ──input──► Agent 6
Agent 6 ──output──► state.milestone_critique ──input──► Assembler
```

### What Each Agent Receives vs. Produces

```
Agent 1 (SpecInterpreter):
  RECEIVES: project_spec (raw)
  PRODUCES: spec_understanding

Agent 2 (SpecClarity):
  RECEIVES: project_spec (raw) + spec_understanding (from Agent 1)
  PRODUCES: spec_clarity (gate decision + questions)

Agent 3 (RoleAgent):
  RECEIVES: project_spec (TRIMMED to role-relevant fields) + spec_understanding
  PRODUCES: identified_roles

Agent 4 (RoleCritic):
  RECEIVES: identified_roles (from Agent 3) + project_spec (trimmed)
  PRODUCES: role_critique (refined roles + corrections_applied)

Agent 5 (MilestonePlanner):
  RECEIVES: project_spec (full) + role_critique (from Agent 4) + spec_understanding (from Agent 1)
  PRODUCES: milestones

Agent 6 (MilestoneReviewer):
  RECEIVES: milestones (from Agent 5 or previous iteration) + project_spec (trimmed) + role_critique + spec_understanding
  PRODUCES: milestone_critique (refined milestones + corrections_applied)

Assembler:
  RECEIVES: project_spec + spec_understanding + role_critique + milestone_critique + metadata
  PRODUCES: final_plan
```

### Context Trimming Strategy

The orchestrator deliberately limits what each agent sees. This is an anti-hallucination technique — giving an agent irrelevant information increases the chance of confabulation.

| Agent | Context Trimming |
|-------|-----------------|
| Agent 3 (Roles) | Only sees: project_name, description, objectives, outcome_per_deliverable, project_goals (if set) |
| Agent 4 (RoleCritic) | Only sees: name, description[:500], objectives |
| Agent 5 (Planner) | Receives full project_spec + spec_understanding + roles |
| Agent 6 (Reviewer) | Only sees: objectives, description[:1000], roles, spec_understanding |
| Agent 1, 2 | Receive full project_spec |

### Type Handling: Fully Typed Pipeline

All core pipeline agents (1-6) accept **typed Pydantic models only** in their `run()` signatures:

```python
# All typed — no Union[Model, Dict] needed
async def run(self, milestones: MilestonesSchema, project_spec: Dict, roles: RefinedRolesSchema, ...)
```

On **fresh runs**, the orchestrator passes typed models directly between agents. On **resume from DB**, `PipelineState.from_dict()` reconstructs typed models via the `_TYPED_FIELDS` registry before the orchestrator reads them. The only place that still accepts both typed models and dicts is `MilestonePlannerAgent.build_prompts()` (a static method shared with the streaming path).

---

## 8. Information Fidelity — How Data Is Faithfully Preserved

The pipeline uses multiple mechanisms to ensure that information from the project spec is accurately carried through all 7 steps without distortion.

### Mechanism 1: Original Spec Passthrough

The original `project_spec` dict is stored in state at initialization and passed to every agent that needs it. Agents receive the original user input directly — they don't rely on a previous agent's interpretation of it.

```
project_spec ──────────────────────────► Agent 1
project_spec ──────────────────────────► Agent 2 (+ Agent 1's understanding)
project_spec (trimmed) ────────────────► Agent 3 (+ Agent 1's understanding)
project_spec (trimmed) ────────────────► Agent 4
project_spec ──────────────────────────► Agent 5 (+ Agent 1's understanding)
project_spec (trimmed) ────────────────► Agent 6 (+ Agent 1's understanding)
project_spec ──────────────────────────► Assembler
```

This prevents the "telephone game" problem where information degrades through repeated summarization. Notably, `spec_understanding` now flows all the way to Agents 5 and 6 — the milestone generator and reviewer receive the refined interpretation alongside the raw spec. This ensures that the consolidated objectives from Agent 1 (especially any clarification-enriched objectives on the resume path) are used as the canonical source of truth for milestone scope and alignment.

### Mechanism 2: Pydantic Schema Enforcement

Every agent output is validated through a Pydantic model with strict constraints:

```python
result = response_model(**parsed_dict)  # Raises ValidationError on bad data
```

Constraints include:
- `Field(..., ge=1)` for numeric minimums
- `Field(..., min_length=1)` for non-empty lists
- `Literal[...]` for enum values
- `@field_validator` for custom rules

If the LLM produces output that violates any constraint, `StructuredOutputError` is raised and the call is retried.

### Mechanism 3: Hard Numeric Invariants

The pipeline enforces mathematical constraints at multiple levels:

| Invariant | Enforced In |
|-----------|------------|
| `milestone_count == N` | Prompt, Planner post-check, Reviewer corrections, Orchestrator `_check_milestone_constraints()`, Assembler `_check_milestone_count()` |
| `SUM(days) == total` | Prompt (self-validation), Planner post-check, Reviewer corrections, Orchestrator `_check_milestone_constraints()`, Assembler `_check_days_sum()` |
| `SUM(rubric_weights) == 100` per milestone | Prompt, Reviewer corrections, Orchestrator `_check_milestone_constraints()`, Assembler `_check_rubric_weights()` |

This is **four layers of enforcement** for the same invariant. If the LLM gets it wrong, the reviewer fixes it. If the reviewer gets it wrong, the orchestrator loops it back. If it still fails, the assembler logs a warning (non-blocking).

### Mechanism 4: Clarification Merge (Resume Path)

When the user answers clarification questions, the answers are appended to the project description:

```python
project_spec["project_description"] += f"\n\nCLARIFICATIONS:\n{user_clarifications}"
```

The spec interpreter is then re-run with `previous_understanding`, producing a **consolidated** understanding that integrates the original spec + the clarification. This merged understanding flows to all downstream agents.

### Mechanism 5: Assembler Cross-Validation

The final step runs 6 warning-level checks that detect information loss:

| Check | What It Detects |
|-------|----------------|
| `_check_skill_coverage()` | Each role's skills appear somewhere in milestone rubric criteria |
| `_check_deliverables_coverage()` | Project spec outcome keys appear in milestone deliverables |
| `_check_deliverables_present()` | Every milestone has non-empty deliverables AND acceptance_criteria |
| `_check_milestone_count()` | Final count matches requested count |
| `_check_days_sum()` | Final days total matches requested total |
| `_check_rubric_weights()` | Each milestone's rubric sums to 100 |

### Mechanism 6: Audit Log

Every state mutation is timestamped:
```python
def update(self, key: str, value: Any):
    if hasattr(self, key):
        setattr(self, key, value)
    self.updated_at = datetime.now(timezone.utc)
    self.audit_log[key] = {
        "updated_at": self.updated_at.isoformat(),
        "value_summary": (
            str(value)[:100] + "..."
            if isinstance(value, str) and len(str(value)) > 100
            else "object" if not isinstance(value, (str, int, float, bool, type(None)))
            else str(value)
        )
    }
```

The `value_summary` logic has three branches: long strings are truncated at 100 characters, complex objects (dicts, Pydantic models, lists) are logged as `"object"` to avoid bloating the audit log, and primitives log their string representation. This creates an immutable record of when each piece of information was written and by which step.

---

## 9. Anti-Hallucination Strategy

Hallucination prevention is a first-class concern in this pipeline. It operates at 7 distinct layers:

### Layer 1: Prompt-Level Instructions

Every agent prompt contains explicit anti-hallucination directives:

| Agent | Directive |
|-------|----------|
| SpecInterpreter | "Extract ONLY information explicitly stated — DO NOT invent features, requirements, or capabilities not mentioned" |
| SpecClarity | "DO NOT re-ask about objectives already extracted" |
| RoleAgent | "Identify roles based on the specification summary — do not hallucinate roles not supported by the text" |
| RoleAgent | "DO NOT invent technologies, frameworks, or tools not mentioned in the specification" |
| MilestonePlanner | "DO NOT invent milestones for features not in objectives or outcome_per_deliverable" |
| MilestoneReviewer | Removes milestones for features not in the original spec (scope validation) |
| ExecutiveSummary | "DO NOT invent metrics, statistics, or claims not in the input" |
| MilestoneCount | "Base reasoning ONLY on provided inputs" |

### Layer 2: Controlled Temperature Settings

| Agent | Temperature | Why |
|-------|------------|-----|
| SpecInterpreter | 0.1 | Pure factual extraction — no creativity needed |
| SpecClarity | 0.2 | Structured decision making |
| RoleAgent | 0.2 | Constrained identification |
| RoleCritic | **0.1** | Cold critic — deterministic systematic critique (colder than RoleAgent) |
| MilestonePlanner | **0.5** | Warm generator — explores diverse decompositions with thinking; constraints enforced by reviewer |
| MilestoneReviewer | **0.1** | Cold critic — deterministic constraint enforcement (colder than MilestonePlanner) |
| OutcomesClarityAgent | 0.0 | Deterministic gate decision |
| Other standalone agents | 0.1-0.4 | Lean toward precision; ExecutiveSummary at 0.4 for natural prose |

The base class default of 0.7 is **never used** in practice. The only agent exceeding 0.3 is MilestonePlannerAgent (0.5), which relies on the MilestoneReviewerAgent (0.1) to enforce constraints downstream. This is the hot/cold generator-critic pattern described in Section 1.

### Layer 3: Context Scoping (Information Diet)

Agents receive only the information they need:

```
Agent 3 (Roles):
  ✓ project_name, description, objectives, outcomes, project_goals
  ✗ timeline, milestone count, budget, company details

Agent 6 (Reviewer):
  ✓ milestones, objectives, description[:1000], roles, spec_understanding
  ✗ full description, company Q&A answers
```

This reduces the surface area for confabulation. An agent can't hallucinate about timeline details if it never sees the timeline.

### Layer 4: Structured Output Enforcement

All LLM outputs are parsed through Pydantic models with strict typing:

```python
# LLM returns "seniority": "expert" → Pydantic rejects it
Role.seniority: Literal["junior", "mid", "senior", "not_specified"]

# LLM returns weight: 150 → Pydantic rejects it
EvaluationRubricItem.weight: int = Field(..., ge=0, le=100)

# LLM returns empty milestones → Pydantic rejects it
Milestone.acceptance_criteria: List[str] = Field(..., min_length=1)
```

When Pydantic validation fails, the call is retried (up to 1 time for schema errors).

### Layer 5: Generator-Critic Pattern

Each major output goes through a critic:

```
RoleAgent output → RoleCriticAgent verifies and corrects
MilestonePlanner output → MilestoneReviewer verifies and corrects
```

Critics are specifically instructed to check for:
- Fabricated technologies/tools not in the spec
- Vague terms (blocklisted: "good", "proper", "appropriate", "complete", "efficient", "clean", "quality")
- Out-of-scope features
- Constraint violations

### Layer 6: In-Prompt Self-Validation

The milestone planner prompt includes a dedicated validation section:
```
VALIDATION (before output):
1. Count milestones — must be exactly {milestones_count}
2. Sum days_allocated — must equal {time_needed_days}
3. Check each rubric — weights must sum to exactly 100
```

This forces the LLM to verify its own output before returning it.

### Layer 7: Project Goals Conditioning

When `project_goals` is present in the spec, Agents 3, 5, and 6 all receive goal-specific instructions that shape their outputs. This reduces hallucination by constraining the solution space:

| Goal | Agent 3 (Roles) | Agent 5 (Planner) | Agent 6 (Reviewer) |
|------|-----------------|-------------------|-------------------|
| `hiring` | Roles emphasize demonstrable skills | Milestones progressively reveal skill depth | Verifies progressive difficulty curve |
| `bounty` | Roles are solution-oriented | Milestones emphasize deliverable quality | Verifies measurable quality criteria |
| `marketing` | Roles include content creation ability | Milestones include reach/engagement tasks | Verifies marketing-relevant metrics |

Without goal conditioning, the planner might generate generic milestones that don't match what the enterprise actually cares about — e.g., creating "documentation milestones" for a hiring-focused project where the enterprise wants to see coding skill progression.

### Hallucination Response Matrix

| Hallucination Type | Detection | Response |
|-------------------|-----------|----------|
| Invented features | Scope validation in reviewer | Reviewer removes the milestone |
| Wrong numeric totals | Pydantic + orchestrator checks | Retry or reviewer auto-fix |
| Vague acceptance criteria | Prompt blocklist + reviewer | Reviewer replaces with measurable terms |
| Fabricated technologies | RoleCritic project alignment check | Critic removes unsupported roles/skills |
| Added assumptions as facts | SpecInterpreter "Assumption:" prefix rule | Forces labeling of any inference |
| Schema violations | Pydantic strict parsing | StructuredOutputError → retry |

---

## 10. The Assembler — Final Plan Construction

`Assembler.assemble_final_plan()` (`assembler.py`) is a **pure Python function** — no LLM calls, no I/O, no side effects. It merges all agent outputs and runs cross-validation.

### Final Plan Structure

```python
{
    "project_spec": project_spec,              # Original enterprise input (preserved verbatim)
    "spec_understanding": spec_understanding,  # SpecUnderstanding dict
    "identified_roles": identified_roles,      # RefinedRolesSchema dict (prefers critic output)
    "milestones": milestones_list,             # List[Milestone dict] from reviewer
    "metadata": {
        "generated_at": "2026-02-22T10:30:45.123456",
        "run_id": "uuid-string",
        "streaming": True                      # Only on streaming path
    },
    "corrections": {                           # Optional — only when corrections exist
        "role_corrections": ["..."],
        "milestone_corrections": ["..."]
    }
}
```

### Cross-Validation Checks (All Warning-Only)

```python
_check_rubric_weights(milestones)              # SUM(weights) == 100 per milestone
_check_days_sum(milestones, project_spec)      # SUM(days) == time_needed_days
_check_milestone_count(milestones, project_spec) # len == milestones count
_check_deliverables_present(milestones)        # Each has deliverables AND criteria
_check_skill_coverage(roles, milestones)       # Role skills appear in rubric text
_check_deliverables_coverage(milestones, spec) # Spec outcomes appear in deliverables
```

Also validates sequential milestone IDs: `sorted(ids) == list(range(1, len+1))`.

These checks NEVER block the output — they only log warnings. This is intentional: it's better to return a slightly imperfect plan than to fail entirely.

---

## 11. Dual Execution Paths: Orchestrator vs Streaming

The pipeline has two execution paths that use the same agent classes but differ in state management and UX.

### Comparison

| Feature | Orchestrator Path | Streaming Path |
|---------|------------------|----------------|
| Entry point | `PipelineOrchestrator.run()` | `StreamingPipelineRunner.run_streaming()` |
| State management | Full `PipelineState` with checkpoints | Stateless — no state object |
| DB persistence | Checkpoints saved after each stage | No DB writes |
| Resume support | Yes (from `STOPPED_AFTER_CLARITY`) | No |
| Output format | Returns `final_plan` dict | Yields SSE events (`AsyncGenerator`) |
| Reviewer loop | Up to 2 iterations with constraint checks | Up to 2 iterations with constraint checks (same logic) |
| Milestone generation | Agent's `run()` method | Direct `LLMProvider.call_streaming()` for live thinking tokens |
| Constraint validation | Full (`validators.py` + assembler) | Full (`validators.py` — shared module) |
| spec_understanding | Threaded to Steps 5, 6 | Threaded to Steps 5, 6 |

### SSE Event Types (Streaming)

| Event | Payload | When |
|-------|---------|------|
| `thinking` | `{"text": "## Step label...\n"}` | Before/during each step |
| `clarification_needed` | `{"questions": {...}, "ready_for_planning": false}` | Clarity gate halts |
| `complete` | `{"result": final_plan}` | Pipeline finished |
| `error` | `{"error": "human-readable message"}` | Any failure |

### Why Milestone Planner Uses Direct Streaming

In the streaming path, Stage 5 (MilestonePlannerAgent) is unique: instead of calling `agent.run()`, it uses `LLMProvider.call_streaming()` directly. This enables **live thinking token streaming** to the UI:

```python
async for chunk_type, chunk_text in llm.call_streaming(...):
    if chunk_type == "thought":
        yield _sse("thinking", {"text": chunk_text})  # Show reasoning live
    else:
        answer_text += chunk_text  # Collect final JSON
```

The `build_prompts()` static method on `MilestonePlannerAgent` is reused to construct identical prompts for both paths.

---

## 12. LLM Infrastructure Layer

### LLM Provider (`llm_provider.py`)

A **flat model registry + unified API**. It does NOT select models — that's the orchestrator's job.

**Supported providers** (all OpenAI-compatible):

| Provider | Key Models | Thinking Support |
|----------|-----------|-----------------|
| DeepSeek | deepseek-chat, deepseek-reasoner | Separate models |
| Qwen/DashScope | qwen3-max, qwen-plus, qwen-flash, deepseek-v3.2 | Hybrid (`enable_thinking: true`) |
| Kimi/Moonshot | kimi-k2.5, kimi-k2, kimi-k2-thinking | Hybrid on k2.5 |
| ZhipuAI | glm-4.7 | Hybrid (`thinking.type: enabled`) |

**Critical behavior — Thinking replaces JSON mode (CLAUDE.md Gotcha #47):**
```python
# In BasePipelineAgent._call_llm_with_json() (base.py)
requires_reasoning = self.task_type in REASONING_TASK_TYPES
enable_thinking = True if requires_reasoning else None
# NOTE: response_format="json_object" is NOT passed — incompatible with thinking
```
The `enable_thinking` flag is set to `True` for reasoning task types (`milestone_review`, `role_critique`, `milestone_planning`) and `None` otherwise. **`response_format="json_object"` is intentionally NOT used** — it is incompatible with thinking mode on Qwen (puts JSON in `reasoning_content`), Kimi (API errors), and ZhipuAI (invalid output). The pipeline always chooses thinking over json_object; JSON structure is enforced via prompt instructions + `_extract_json_from_text()` fallback + `call_with_retry()`.

**Thinking budget propagation (CLAUDE.md Gotcha #48):**
Agents set `thinking_budget` alongside `max_tokens`. The `_call_model_by_name()` router in `llm_provider.py` translates these per-provider: Qwen uses a separate `thinking_budget` parameter; Kimi/ZhipuAI inflate `max_tokens` by adding `thinking_budget`; DeepSeek ignores it (reasoner always thinks). Agents should set `max_tokens` based on answer-only estimates.

**Fallback chain:** If the requested model fails, iterate through ALL registered models and return the first success. If all fail → `LLMProviderError`.

### LLM Orchestrator (`llm_orchestrator.py`)

Selects which model to use based on `TaskContext`:

```
TaskContext(task_type, requires_reasoning, user_tier, is_pay_as_you_go, pipeline_strategy)
```

**Reasoning task types** (set `enable_thinking=True` + unlock reasoning-class models for Pro/Business tiers):
- `milestone_review`
- `role_critique`
- `milestone_planning`

> **Note:** Being in `REASONING_TASK_TYPES` does two things: (1) sets `enable_thinking=True` on the LLM call, and (2) for Pro tier with `reasoning_on_demand=True`, adds the REASONING cost class to the allowed models. Launch-tier users still get economy models even for these tasks — `enable_thinking` is sent but capped by model capability. See Section 6 "Model Selection Is Tier-Dependent" for the full mapping.

**Model selection algorithm:**
1. Resolve tier (apply PAYG bump if applicable)
2. Determine strategy (per-request override or tier default)
3. Look up task preferences for the strategy
4. Filter by allowed model classes + cost priority
5. Return first available model
6. If none → strategy fallback list → tier last resort (e.g., `qwen-flash`)

### PAYG Flag Propagation Path

```
API request → PipelineService → PipelineOrchestrator → Agent constructor
→ BasePipelineAgent → TaskContext → LLMOrchestrator.select_model()
```

Missing `is_pay_as_you_go` at any layer silently degrades to the base tier model.

---

## 13. Persistence and Resume

### Database Table: `pipeline_states`

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID | Primary key |
| `user_id` | UUID | Owner |
| `project_id` | UUID? | Associated project (nullable) |
| `state_data` | JSONB | Full `PipelineState.to_dict()` blob |
| `pipeline_stage` | str | Current stage (indexed for active-state queries) |
| `expires_at` | timestamp | TTL for auto-expiry |
| `created_at` / `updated_at` | timestamp | Audit timestamps |

### Resume Flow

```
1. User submits clarification answers
2. PipelineService loads state from DB by state_id
3. Restores PAYG params from saved state (user_tier, pipeline_strategy, is_pay_as_you_go)
4. Creates PipelineOrchestrator with restored params
5. Calls orchestrator.run() with initial_state + user_clarifications
6. Orchestrator detects STOPPED_AFTER_CLARITY stage
7. Merges clarifications into project_description
8. Re-runs SpecInterpreter with previous_understanding
9. Skips clarity gate (sets stage to CLEAR_TO_CONTINUE)
10. Continues pipeline from Step 3 (Roles) through Step 7 (Assembler)
11. On success: deletes state from DB (prevents orphaned states)
```

### Checkpoint Recovery Flow

When a pipeline fails mid-execution (e.g., LLM rate limit at Step 5), the error state is persisted to DB. On retry, the orchestrator skips already-completed stages:

```
1. Pipeline fails at Step 5 (MILESTONE_PLANNING)
2. _persist_error_state() saves state with pipeline_stage = "ERROR_AT_MILESTONE_PLANNING"
3. State includes last_checkpoint_stage = "ROLES_REFINED" (from Step 4)
4. User clicks "Generate" again → PipelineService detects ERROR_AT_* state
5. Service loads checkpoint_state, deletes error record, creates new orchestrator
6. Orchestrator receives initial_state → from_dict() reconstructs typed models
7. Checkpoint detection: last_checkpoint_stage ("ROLES_REFINED") >= CLEAR_TO_CONTINUE → resume
8. _stage_completed("ROLES_REFINED") = True → skip Steps 3-4, load refined_roles from state
9. _stage_completed("MILESTONES_REVIEWED") = False → run Steps 5-6 fresh
10. Step 7 (Assembly) always runs (cheap, stateless)
```

Stage ordering used by `_stage_completed()`:
```
INITIAL → SPEC_INTERPRETED → CLEAR_TO_CONTINUE → ROLES_REFINED → MILESTONES_REVIEWED → COMPLETED
```

If the error state has no `last_checkpoint_stage` (failure before any checkpoint), the service deletes the record and starts fresh.

### Idempotency Check

Before starting a new pipeline run, `PipelineService` checks for existing active states:

```python
existing = await pipeline_state_repo.get_active_state(user_id, project_id)
if existing and existing["pipeline_stage"] == "STOPPED_AFTER_CLARITY":
    return existing_clarity_questions  # Don't re-run, return saved questions
if existing and existing["pipeline_stage"].startswith("ERROR_AT_"):
    if existing["state_data"]["last_checkpoint_stage"]:
        resume_from_checkpoint(existing)  # Skip completed stages
    else:
        delete_and_start_fresh(existing)
if existing and existing["status"] == "in_progress":
    raise HTTP 409 Conflict  # Another run is already in progress
```

### BOLA Protection

```python
if str(state.user_id) != str(user_id):
    raise HTTP 403 Forbidden
```

---

## 14. Known Limitations, Resolved Issues, and Lessons Learned

### Current Technical Debt

**1. Streaming Path Has No Persistence**

The `StreamingPipelineRunner` is intentionally stateless — no `PipelineState`, no checkpoints, no database writes. If the SSE stream disconnects mid-pipeline, the entire run is lost and must be retried from scratch. This is acceptable for the current UX (streaming is used for real-time progress display) but may need addressing if streaming becomes the primary path.

**2. `build_prompts()` Duck-Typing**

`MilestonePlannerAgent.build_prompts()` is the only method that still uses `hasattr(obj, "model_dump")` duck-typing to accept both typed models and raw dicts. This exists because the streaming path may pass dicts. If the streaming path is ever made type-safe, this can be simplified.

**3. LLM Timeout for Complex Prompts**

The default LLM timeout is 120s (`LLM_TIMEOUT_SECONDS` in `config.py` — CLAUDE.md Gotcha #11). For projects with many milestones (8-10), the MilestonePlannerAgent with thinking enabled can approach this limit. Consider increasing per-agent or making it configurable per task type.

---

### Resolved Issues (Historical)

<details>
<summary>Click to expand resolved issues from 2026-02-23</summary>

#### 1. ~~Checkpoint Recovery Was Write-Only~~ (RESOLVED 2026-02-23)

The orchestrator now supports full checkpoint recovery. `STAGE_ORDER` defines stage progression; `_stage_completed()` skips already-completed stages on resume. The service layer detects `ERROR_AT_*` states, loads the saved `initial_state`, and the orchestrator skips to the first uncompleted stage. See Section 13.

#### 2. ~~Reviewer Loop Feedback Gap~~ (RESOLVED 2026-02-23)

`MilestoneReviewerAgent.run()` now accepts `previous_corrections` and `remaining_violations` parameters. On iteration 2, the orchestrator passes the corrections from iteration 1 and the remaining constraint violations, giving the reviewer full context about prior attempts. Same pattern applied to the streaming runner.

#### 3. ~~Streaming Path Skipped Constraint Validation~~ (RESOLVED 2026-02-23)

The streaming runner now implements the same reviewer retry loop (up to 2 iterations) and delegates constraint checking to the shared `validators.py` module. Both execution paths now have identical constraint enforcement.

#### 4. ~~Temperature Inconsistency in Streaming~~ (RESOLVED 2026-02-23)

`MilestonePlannerAgent.TEMPERATURE` class constant (0.5) is now referenced by both the orchestrator path (via constructor) and the streaming path (via `MilestonePlannerAgent.TEMPERATURE`). No more hardcoded temperature in `streaming_runner.py`.

#### 5. ~~State Stored Dicts, Not Typed Models~~ (RESOLVED 2026-02-23)

`PipelineState` fields are now typed Pydantic models. `from_dict()` reconstructs typed models from DB dicts via `_TYPED_FIELDS` ClassVar mapping and `model_validate()`. Agent signatures use clean typed-only parameters (no more `Union[Model, Dict]`). The `_typed_understanding` workaround in the orchestrator was eliminated.

#### 6. ~~No Dead Letter Queue~~ (RESOLVED 2026-02-23)

`_persist_error_state()` saves error state to DB after any stage failure. The service layer's idempotency check detects `ERROR_AT_*` states and either resumes from the last checkpoint (if available) or clears and starts fresh.

</details>

---

### Lessons Learned from CLAUDE.md Gotchas

These bugs were discovered during development and are now codified as project-wide gotchas. They are documented here because they directly affect the pipeline architecture.

| Gotcha # | Title | Impact on Pipeline | Resolution |
|----------|-------|-------------------|------------|
| **#46** | Pydantic v2 ClassVar for Class Constants | `_TYPED_FIELDS` on `PipelineState` was initially a plain annotated dict, which Pydantic v2 treated as `ModelPrivateAttr` — `.items()` calls failed at runtime | Annotated with `ClassVar[Dict[str, type]]` so Pydantic ignores it entirely |
| **#47** | `json_object` Incompatible with Thinking Mode | Pipeline originally used `response_format="json_object"`. On Qwen, Kimi, ZhipuAI: JSON ended up in `reasoning_content`, API errors, or invalid output — thinking mode was silently suppressed | Removed `response_format="json_object"` entirely. JSON is now enforced via prompt instructions + `_extract_json_from_text()` fallback + retry. Thinking mode is always preserved for reasoning tasks |
| **#48** | Provider-Specific `max_tokens` Semantics | With thinking enabled, `max_tokens` means different things per provider (Qwen: answer-only, Kimi/ZhipuAI: shared with thinking). Agents were setting `max_tokens` too low for providers that share the budget, causing truncated outputs | Added `thinking_budget` parameter to `BasePipelineAgent`. The `_call_model_by_name()` router in `llm_provider.py` inflates `max_tokens` for providers without separate budgets |
| **#37** | PAYG Flag Threading Pattern | `is_pay_as_you_go` must propagate through 8+ layers: Frontend → API → Pydantic → Service → Orchestrator → Agent → TaskContext → LLMOrchestrator. Missing it at any layer silently degrades to base tier | All agent constructors accept PAYG params; orchestrator passes them to every agent; state persists them across pause/resume |
| **#4** | Pipeline Stops on Unclear Spec | If `SpecClarityAgent` returns `ready_for_planning=False`, the pipeline halts. Early users were confused by silent failures | Explicit status `stopped_for_clarification` in state; service layer returns `PipelineClarityQuestionsResponse` with questions |
| **#10** | UUID Serialization | Pydantic models with UUIDs fail standard `json.dumps()` | `to_dict()` uses `model_dump(mode='json')` which serializes UUIDs to strings; `to_json()` has a custom serializer for UUID/datetime |

---

## 15. Essential Files Quick Reference

For onboarding, read these files in this order:

| Priority | File | Why Read It |
|----------|------|-------------|
| 1 | `state.py` | Understand what data flows through the system |
| 2 | `base.py` | Understand how agents call LLMs and parse responses |
| 3 | `orchestrator.py` | Understand the 7-step coordination and constraint loops |
| 4 | `milestone_planner_prompt.md` | See the most complex prompt with constraints and self-validation |
| 5 | `milestone_reviewer_prompt.md` | See what the critic corrects and how |
| 6 | `milestone_schemas.py` | Core data contracts: Milestone, EvaluationRubricItem |
| 7 | `critic_schemas.py` | How corrections_applied extends base schemas |
| 8 | `assembler.py` | Final plan structure and all cross-validation checks |
| 9 | `validators.py` | Shared constraint checks used by both orchestrator and streaming paths |
| 10 | `spec_interpreter.py` | Title override pattern and factual extraction |
| 11 | `spec_clarity.py` | Gate decision logic and question generation |
| 12 | `streaming_runner.py` | Differences from orchestrator path, SSE events |
| 13 | `milestone_pipeline_service.py` | HTTP adapter: idempotency, resume, PAYG threading |
| 14 | `llm_provider.py` | Multi-provider registry, thinking mode mechanics |
| 15 | `llm_orchestrator.py` | Model selection algorithm, PAYG tier bumping |
| 16 | `pipeline_state_repository.py` | DB schema, expiry filtering, checkpoint updates |
| 17 | `task_context.py` | REASONING_TASK_TYPES — which agents get thinking models |

---

## Appendix A: Data Flow Diagram (Complete)

```
[Enterprise User]
       │
       ▼
  ProjectSpec (validated by Pydantic)
       │
       ▼
  PipelineService.generate_plan()
  ├── Idempotency check (DB lookup)
  ├── PAYG param extraction
  └── PipelineOrchestrator(user_tier, strategy, payg)
       │
       ▼
  Step 1: SpecInterpreterAgent
  ├── IN:  project_spec (raw dict)
  ├── LLM: temp=0.1, prompt-enforced JSON, spec_interpretation task
  ├── OUT: SpecUnderstanding (typed model)
  ├── STATE: spec_understanding = SpecUnderstanding (stored typed)
  └── CHECKPOINT: SPEC_INTERPRETED
       │
       ▼
  Step 2: SpecClarityAgent
  ├── IN:  project_spec + SpecUnderstanding
  ├── LLM: temp=0.2, prompt-enforced JSON, spec_clarity task
  ├── OUT: SpecClarity { ready_for_planning, questions_for_company }
  ├── STATE: spec_clarity = SpecClarity (stored typed)
  └── GATE: if not ready → STOP, save state to DB, return questions
       │
       ▼ (ready_for_planning == true)
  Step 3: RoleAgent  [SKIP if checkpoint >= ROLES_REFINED]
  ├── IN:  project_spec (TRIMMED) + SpecUnderstanding
  ├── LLM: temp=0.2, prompt-enforced JSON, role_identification task
  ├── OUT: IdentifiedRoles { roles[], skills_tags[] }
  ├── VALIDATE: at least 1 role
  └── STATE: identified_roles = IdentifiedRoles (stored typed)
       │
       ▼
  Step 4: RoleCriticAgent  [SKIP if checkpoint >= ROLES_REFINED]
  ├── IN:  IdentifiedRoles + project_spec (trimmed)
  ├── LLM: temp=0.1, thinking=True (budget=2048), role_critique task (REASONING MODEL)
  ├── OUT: RefinedRolesSchema { roles[], skills_tags[], corrections_applied[] }
  ├── STATE: role_critique = RefinedRolesSchema (stored typed)
  └── CHECKPOINT: ROLES_REFINED
       │
       ▼
  Step 5: MilestonePlannerAgent  [SKIP if checkpoint >= MILESTONES_REVIEWED]
  ├── IN:  project_spec (full) + RefinedRolesSchema + SpecUnderstanding
  ├── LLM: temp=0.5 (warm), thinking=True (budget=4096), milestone_planning task (REASONING MODEL)
  ├── PROMPT INJECTION: {milestones_count}, {time_needed_days}
  ├── OUT: MilestonesSchema { milestones[] }
  ├── VALIDATE: at least 1 milestone
  └── STATE: milestones = MilestonesSchema (stored typed)
       │
       ▼
  Step 6: MilestoneReviewerAgent [LOOP x2]  [SKIP if checkpoint >= MILESTONES_REVIEWED]
  ├── IN:  MilestonesSchema + project_spec (trimmed) + RefinedRolesSchema + SpecUnderstanding
  │        + previous_corrections + remaining_violations (on retry iteration)
  ├── LLM: temp=0.1 (cold), thinking=True (budget=4096), milestone_review task (REASONING MODEL)
  ├── OUT: RefinedMilestonesSchema { milestones[], corrections_applied[] }
  ├── CHECK: check_milestone_constraints(count, days, rubric_weights) [shared validators.py]
  ├── IF violations AND not last iteration → feed milestones + corrections context back into loop
  ├── STATE: milestone_critique = RefinedMilestonesSchema (stored typed)
  └── CHECKPOINT: MILESTONES_REVIEWED
       │
       ▼
  Step 7: Assembler.assemble_final_plan()
  ├── IN:  project_spec + spec_understanding + role_critique + milestone_critique
  ├── CROSS-VALIDATE: 6 checks (all warning-only)
  ├── OUT: final_plan dict
  └── STATE: final_plan = final_plan, status = "completed"
       │
       ▼
  PipelineService → PipelinePlanResponse → HTTP 200
```

---

## Appendix B: Adding a New Agent — Checklist

When adding a new agent to the pipeline:

1. **Create the agent file** in `agents/autonomous/milestone_pipeline/agents/`
2. **Create the Pydantic schema** in `schemas/milestone_pipeline/` — define exact JSON structure
3. **Create the prompt file** in `agents/prompts/milestone_pipeline/` — include anti-hallucination directives
4. **Inherit `BasePipelineAgent`** — override `temperature`, `max_tokens`, `task_type`, `thinking_budget` (if reasoning task)
5. **Implement `run()`** — load prompt, construct context, call `call_with_retry()`, return typed model
6. **Register task type** in `task_context.py` — add to `TaskType` literal and `REASONING_TASK_TYPES` if needed
7. **Wire into orchestrator** — instantiate in `__init__`, add step in `run()`, update state
8. **Add cross-validation** in `assembler.py` if the new agent's output has verifiable properties
9. **Export** from `agents/__init__.py` and `milestone_pipeline/__init__.py`
10. **Thread PAYG flag** if the agent makes LLM calls (CLAUDE.md Gotcha #37)

---

## Appendix C: Glossary

| Term | Definition |
|------|-----------|
| **Pipeline** | The complete 7-step process from ProjectSpec to final_plan |
| **Orchestrator** | The coordinator that runs agents in sequence and manages state |
| **Gate** | A decision point that can halt the pipeline (Agent 2: SpecClarityAgent) |
| **Critic** | An agent that receives another agent's output and corrects it |
| **Checkpoint** | A durable save of pipeline state to the database |
| **Resume** | Continuing a pipeline from STOPPED_AFTER_CLARITY with user clarifications |
| **Assembler** | Pure Python merge of all outputs into the final plan |
| **Context trimming** | Deliberately limiting what information an agent receives |
| **PAYG** | Pay-as-you-go — a billing flag that upgrades the LLM tier |
| **SSE** | Server-Sent Events — the streaming protocol for live progress updates |
| **Thinking tokens** | LLM reasoning traces streamed live in the streaming path |
| **Corrections_applied** | Audit trail field on critic outputs listing what changed and why |
