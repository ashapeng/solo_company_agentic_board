# Hermes Integration Guidebook

> Design guide for keeping Agentic Board as the council service while using Hermes as the
> evolving agent runtime around it.
>
> Reviewed against Hermes public docs and GitHub on 2026-04-11.
> Build plan updated for C-suite board sequencing on 2026-04-12.

---

## 0. Executive Thesis

Do not replace Agentic Board with Hermes.

Agentic Board is a specialized council service. It has a deliberate governance protocol:
independent analysis, anonymized peer review, chair synthesis, optional verification, and
State of the Board memory.

Hermes is a broader agent runtime. It provides the operating layer that Agentic Board does
not try to be: skills, memory, tools, plugins, session search, gateway surfaces, cron jobs,
delegation, and action execution.

The right architecture is:

```text
Hermes agent runtime
  -> loads business skills and compact memory
  -> decides when a board decision is needed
  -> invokes Agentic Board as a tool/service
  -> stores approved learnings as skills or memory
  -> uses tools/workflows to execute the board decision

Agentic Board council service
  -> deliberates over high-leverage decisions
  -> produces board decisions, risk registers, dissent, and SOTB proposals
  -> remains auditable, deterministic in flow, and separable from action execution
```

The important separation is governance vs. operations:

| Layer | Owns | Should Not Own |
|-------|------|----------------|
| Agentic Board | Judgment, dissent, decisions, institutional board memory | Autonomous task execution, tool sprawl, long-running operations |
| Hermes | Skills, tools, memory, workflows, execution, recall | The internal council protocol or board-member deliberation semantics |
| Human founder | Final authority, memory approval, role evolution, product judgment | Low-level repeated orchestration |

---

## 1. Sources Consulted

Primary sources:

- Hermes README: https://github.com/NousResearch/hermes-agent
- Hermes architecture docs: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture
- Hermes skills docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- Hermes memory docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- Hermes tools docs: https://hermes-agent.nousresearch.com/docs/user-guide/features/tools
- Hermes session storage docs: https://hermes-agent.nousresearch.com/docs/developer-guide/session-storage
- gstack README: https://github.com/garrytan/gstack
- gstack architecture: https://raw.githubusercontent.com/garrytan/gstack/main/ARCHITECTURE.md

Local project references:

- `CLAUDE.md`
- `server/board/orchestrator.py`
- `server/board/classifier.py`
- `server/board/memory.py`
- `server/board/loader.py`
- `server/protocols/stage3_synthesis.md`
- `server/members/*.md`

---

## 2. What Hermes Is

Hermes should be understood as an agent operating system, not merely a prompt library.

### 2.1 Runtime

Hermes has a main agent loop that assembles context, calls models, handles tool calls, and
persists sessions. It is designed to run across CLI and gateway surfaces such as messaging
platforms.

The architecture matters for this project because it provides a host around the board:

- Provider/model resolution.
- Prompt assembly from personality, memory, skills, context files, and session history.
- Tool dispatch and toolsets.
- Session persistence and search.
- Plugins and external integrations.
- Cron jobs and outbound messaging.
- Delegation and subagent orchestration.

Agentic Board already has its own orchestration loop. That loop should not be dissolved into
Hermes. The board's stages are the product.

### 2.2 Skills

Hermes skills are procedural knowledge units loaded on demand. This maps directly to the
"company can evolve" requirement.

In this project, a skill should not be "a board member." A board member already exists as a
council role in `server/members/*.md`.

Instead, Hermes skills should be operating playbooks:

- "When to call the board."
- "How to run a market decision."
- "How to convert a board decision into a sprint plan."
- "How to evaluate whether a new board member should be created."
- "How to update company memory safely."
- "How to run customer discovery."
- "How to run product review."

The board remains a service; skills describe when and how to use it.

### 2.3 Memory

Hermes memory is compact, curated, and injected into the system prompt. It is not a dump of
all prior sessions.

This is a strong corrective to the current SOTB approach. The current SOTB can become stale,
overwritten, or structurally damaged if freeform updates are applied blindly. Hermes'
philosophy is closer to: save high-signal facts, enforce capacity, consolidate entries, and
scan for unsafe content before injecting memory into the prompt.

For Agentic Board, use three memory classes:

| Memory Class | Owner | Storage | Approval |
|--------------|-------|---------|----------|
| Board memory | Agentic Board | `server/memory/sotb.md` and session JSON | Human-approved |
| Operating memory | Hermes | Hermes memory store | Human-approved for material company facts |
| Session recall | Hermes | SQLite/FTS session history | Automatic, but not treated as truth |

### 2.4 Tools And Plugins

Hermes tools are how the agent acts. The tools docs describe toolsets for web, terminal,
files, browser automation, media, delegation, memory, session search, cron jobs, messaging,
and integrations.

This is why Hermes should sit outside the board. The board should not gain unrestricted
terminal, browser, cron, or messaging powers. Those belong in the operating agent layer, after
the board has made a decision.

A Hermes plugin can later expose Agentic Board as a first-class Hermes tool:

```text
agentic_board.deliberate(query, members, full_board, verify)
agentic_board.read_sotb()
agentic_board.propose_sotb_update(update)
agentic_board.list_members()
```

Start with a skill that calls the existing CLI/API. Build a plugin only after the invocation
pattern is stable.

### 2.5 Session Storage And Recall

Hermes uses SQLite with FTS5 for persisted sessions and search. This is materially different
from the current `data/sessions/*.json` history.

Agentic Board should keep JSON sessions as board audit artifacts. Hermes should provide
cross-session recall, discovery, and search across broader operating conversations.

Do not make session search authoritative memory. Treat it as evidence retrieval:

```text
Hermes session search -> possible prior context -> board or human verifies -> approved memory
```

---

## 3. Why Build Hermes Around This Project

The current project has a strong council but a weak growth mechanism.

The board can deliberate, but it does not yet have a principled way to:

- Learn operating procedures after repeated work.
- Decide when a new specialist is justified.
- Convert decisions into recurring workflows.
- Retrieve lessons from many prior sessions.
- Execute actions through safe tools.
- Update memory without poisoning or drift.
- Track when a role, skill, or company assumption became stale.

Hermes answers those gaps if it is used carefully.

### 3.1 The Board Solves Judgment

The board is useful when a decision needs dissent, synthesis, and memory:

- Strategic direction.
- Product positioning.
- MVP scope.
- Market entry.
- Technical tradeoffs.
- Risk assessment.
- Security/operations readiness once those members are active.

### 3.2 Hermes Solves Repeated Operations

Hermes is useful when a process repeats:

- Prepare context for a board meeting.
- Summarize customer notes into board-ready evidence.
- Turn a board decision into a task plan.
- Run follow-up research.
- Search prior sessions for related decisions.
- Maintain small memories and reusable skills.
- Schedule follow-up reviews.

### 3.3 gstack's Lesson

gstack's relevant lesson is not its exact toolchain. The lesson is that agent teams become
more useful when knowledge is encoded as composable process skills. The flow is procedural:
think, plan, build, review, test, ship, reflect.

For this repo, use that lesson as:

```text
Board decision -> Hermes operating skill -> execution workflow -> review -> memory/skill update
```

Do not turn every gstack-style specialist into a board member. Board roles and operating roles
are different jobs.

---

## 4. Philosophy For Hermes In Agentic Board

### 4.1 Keep The Board Small And Serious

Adding agents is not evolution by itself. It is often just cost and noise.

A new board member should require a persistent decision gap, not a one-off task. Examples:

- Add Finance when pricing, runway, and margin decisions become recurring.
- Add Legal/Compliance when contracts, regulated data, or liability become recurring.
- Activate Guardian when the product handles user data or external integrations.
- Activate Operator when the product ships to real users.

Use Hermes skills for temporary procedures. Use board members for durable governance voices.

### 4.2 Make Skills The Evolving Surface

Most evolution should happen in skills, not member prompts.

Member prompts define worldview and decision boundaries. Skills define procedures that can
change as the business learns.

Example:

```text
Stable board member:
  Product Lead: "What is the smallest thing users will pay for?"

Evolving Hermes skills:
  customer_interview_synthesis
  pricing_experiment_design
  onboarding_dropoff_diagnosis
  launch_retrospective
  board_decision_to_sprint_plan
```

### 4.3 Memory Is A Contract, Not A Log

The board should not remember everything. It should remember commitments, decisions,
validated facts, active risks, and unresolved questions.

Hermes can search logs. SOTB should contain only the durable truths that should steer future
decisions.

### 4.4 Evolution Requires Governance

Hermes can propose changes. It should not silently rewrite the company's constitution.

Require approval for:

- Adding or removing a board member.
- Changing a board member's core question or domain boundaries.
- Promoting a workflow from ad hoc to standard skill.
- Writing durable company memory.
- Changing SOTB decisions, risk register, or established positions.

Allow automatic updates for:

- Non-durable session summaries.
- Candidate skill drafts.
- Evaluation artifacts.
- Search indexes.
- Runtime telemetry.

### 4.5 Tools Belong Outside The Council

Board members should not browse, edit files, schedule messages, or execute terminal commands
during deliberation unless the deliberation protocol explicitly adds a research/tool stage.

Reason: tools collapse the boundary between evidence gathering, judgment, and action. The
current council pattern is strongest because members reason independently from the same
evidence packet and then challenge each other.

Hermes should gather evidence before the board and execute after the board.

---

## 5. Target Architecture

### 5.1 Component Diagram

```text
                         Human Founder
                              |
                              v
                    Hermes CLI / Gateway / UI
                              |
                              v
                 +---------------------------+
                 | Hermes Runtime            |
                 | - skills                  |
                 | - compact memory          |
                 | - tools/toolsets          |
                 | - session search          |
                 | - plugins                 |
                 | - cron/messaging          |
                 +-------------+-------------+
                               |
                               | board decision needed
                               v
                 +---------------------------+
                 | Agentic Board Adapter     |
                 | Skill first, plugin later |
                 +-------------+-------------+
                               |
                 CLI/API call  |  HTTP or Python package call
                               v
                 +---------------------------+
                 | Agentic Board Service     |
                 | - classifier              |
                 | - member loader           |
                 | - 3+1 stage orchestrator  |
                 | - compaction              |
                 | - verification            |
                 | - SOTB proposals          |
                 +-------------+-------------+
                               |
                               v
                 +---------------------------+
                 | Board Artifacts           |
                 | - session JSON            |
                 | - board decision          |
                 | - verification result     |
                 | - proposed SOTB diff      |
                 +-------------+-------------+
                               |
              approval gate    v
                 +---------------------------+
                 | Durable Knowledge         |
                 | - SOTB                    |
                 | - Hermes memory           |
                 | - Hermes skills           |
                 | - evaluation benchmarks   |
                 +---------------------------+
```

### 5.2 Data Flow: Board Decision

```text
1. User asks Hermes a business question.
2. Hermes loads relevant memory and skills.
3. Hermes decides whether the question needs:
   - direct answer,
   - operating workflow,
   - board deliberation.
4. If board deliberation is needed, Hermes invokes Agentic Board:
   - query,
   - optional member_ids,
   - full_board flag,
   - verify flag.
5. Agentic Board runs its normal council protocol.
6. Agentic Board returns:
   - board decision,
   - dissenting views,
   - risks,
   - next steps,
   - verification result,
   - proposed SOTB update.
7. Hermes presents the decision and proposed memory updates to the user.
8. User approves/rejects durable memory changes.
9. Hermes executes follow-up skills only after approval or explicit user instruction.
```

### 5.3 Data Flow: Skill Evolution

```text
1. Hermes completes a recurring workflow three or more times.
2. Hermes identifies repeatable procedure and proposes a skill draft.
3. Board is invoked only if the skill changes company strategy or governance.
4. Human reviews the skill.
5. Approved skill is stored in the Hermes skills directory.
6. Skill usage is evaluated over future sessions.
7. Hermes proposes refinements based on observed failures.
```

### 5.4 Data Flow: Board Roster Evolution

```text
1. Hermes or the board detects a repeated blind spot.
2. Hermes drafts a "role gap memo":
   - missed decision type,
   - affected sessions,
   - current role that tried to cover it,
   - proposed new member or skill,
   - cost/latency impact.
3. Board deliberates on whether this is a durable governance role.
4. Human approves one of:
   - create a Hermes skill only,
   - activate shelved member,
   - create new board member,
   - do nothing.
5. If approved, update member files and classifier metadata.
6. Add benchmark queries to prove the new role improves outcomes.
```

---

## 6. Integration Options

### Option A: Hermes Skill Calling The Existing CLI

This is the first Hermes implementation target after the board contract, memory gate, and
roster/routing prerequisites are fixed.

Shape:

```text
hermes/skills/agentic-board/SKILL.md       # source-controlled repo copy
~/.hermes/skills/agentic-board/SKILL.md    # installed Hermes source of truth
  -> explains when to invoke the board
  -> calls local command:
     .venv/bin/python -m server.cli --verify --budget "<question>"
```

Hermes' default skill source of truth is `~/.hermes/skills/`. To keep this project
source-controlled, either sync the repo skill into that directory or configure Hermes to scan
this repo's `hermes/skills/` directory as an external skill directory.

Pros:

- No changes to Agentic Board internals.
- Fastest path to validate the workflow.
- Keeps Hermes optional.
- Failure mode is simple: the skill call fails or returns CLI output.

Cons:

- CLI output is human-oriented, not a stable tool contract.
- Harder to parse session IDs and structured result fields.
- Requires local working directory and environment setup.

Use this while learning the invocation patterns.

### Option B: Hermes Skill Calling The Existing API

Shape:

```text
Hermes skill
  -> ensure Agentic Board server is running
  -> POST /deliberate or /deliberate/stream
  -> read session JSON from response
```

Pros:

- More structured than CLI.
- Uses existing FastAPI interface.
- Can be used from non-local Hermes surfaces if secured.

Cons:

- Requires server lifecycle management.
- Current API has permissive CORS and no auth; do not expose publicly as-is.
- SOTB update endpoint allows direct writes and must be gated before deployment.

Use this when Hermes and board run on the same trusted machine.

### Option C: Hermes Plugin With A First-Class Tool

Shape:

```text
Hermes plugin:
  tool: agentic_board_deliberate
  input schema:
    query: string
    member_ids: list[string] | null
    full_board: bool
    verify: bool
  output schema:
    session_id: string
    decision: string
    risks: list
    dissent: list
    next_steps: list
    proposed_sotb_update: string | null
    verification: object | null
```

Pros:

- Best long-term contract.
- Hermes can reason over structured board outputs.
- Enables clean logging, approvals, and memory update flows.

Cons:

- Requires plugin implementation and maintenance.
- Premature before the board output schema is stable.
- Needs security review if tools can mutate memory or files.

Build this only after Option A or B has been used successfully for several real decisions.

### Option D: Embed Hermes Inside Agentic Board

Do not do this now.

Embedding Hermes inside the orchestrator would blur the core council protocol. It would also
mix tool execution, session memory, skill evolution, and governance into the board service.

That is exactly the complexity boundary this design is trying to avoid.

---

## 7. Proposed Repository Additions

Keep Hermes-specific files separate from the board engine.

```text
docs/
  HERMES_INTEGRATION_GUIDEBOOK.md

hermes/
  skills/
    agentic-board/
      SKILL.md
    board-decision-to-sprint/
      SKILL.md
    board-memory-update/
      SKILL.md
  plugins/
    agentic_board/
      README.md
      plugin.py                  # future only
      schemas.py                 # future only
  examples/
    board_decision_request.json
    board_decision_response.json

server/
  board/
    schemas.py                   # future: stable BoardSession API schema
    memory_review.py             # future: proposed SOTB diffs and approvals
```

Do not move `server/members/*.md` into Hermes skills. They are not the same abstraction.

---

## 8. Skill Design

### 8.1 First Skill: `agentic-board`

Purpose: decide when to invoke the board and how to handle the result.

Draft structure:

```markdown
---
name: agentic-board
description: Invoke the local Agentic Board council service for high-leverage company decisions.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [company, board, strategy, decisions]
    category: business-ops
    requires_toolsets: [terminal]
---

# Agentic Board Skill

## When To Use
- Strategic or product decisions with unclear tradeoffs.
- Decisions where dissent matters.
- Decisions that should update durable company memory.
- Major technical choices with product or market consequences.

## When Not To Use
- Simple factual lookups.
- Small implementation tasks.
- One-off formatting or writing.
- Tasks that can be handled by an existing operating skill.

## Procedure
1. Clarify the actual decision if the user request is ambiguous.
2. Determine whether to use full board or selected members.
3. Invoke Agentic Board with verification enabled for high-impact decisions.
4. Summarize the board decision.
5. Present SOTB updates as proposed changes, not automatic truth.
6. Ask for approval before writing durable memory.
7. Convert approved next steps into an operating workflow.

## Failure Modes
- Board returns a summary instead of a decision.
- Classifier excludes an important role.
- SOTB update is too broad or unsupported.
- Decision needs external evidence that was not provided.
```

### 8.2 Operating Skills

Create these after the first board skill works:

| Skill | Purpose |
|-------|---------|
| `board-decision-to-sprint` | Convert board output into scoped execution plan |
| `board-memory-update` | Review proposed SOTB and Hermes memory changes |
| `customer-evidence-packet` | Prepare customer evidence before a board decision |
| `role-gap-review` | Decide whether repeated blind spots require a new member |
| `strategy-retro` | Compare prior board decisions against outcomes |

### 8.3 Skill Promotion Rule

A workflow becomes a skill only if:

1. It was used at least three times.
2. It has a repeatable procedure.
3. It produced better output than ad hoc prompting.
4. It has clear "when not to use" boundaries.
5. It does not belong as a board member instead.

---

## 9. Memory Architecture

### 9.1 SOTB Should Become Section-Aware

Current SOTB should evolve from a freeform last-session update into a structured memory file:

```markdown
# State of the Board

## Active Decisions
- [date] [decision_id]: Decision, rationale, owner, review date.

## Risk Register
- [risk_id]: Risk, probability, impact, mitigation, owner, status.

## Established Positions
- Position, evidence, confidence, reversal condition.

## Open Questions
- Question, why it matters, evidence needed, owner.

## Last Session
- Session id, decisions made, unresolved issues.
```

### 9.2 Memory Update Flow

```text
Chair proposes SOTB Update
  -> parser extracts candidate update
  -> memory reviewer converts to structured diff
  -> Hermes presents diff to human
  -> human approves/rejects/edits
  -> SOTB write occurs
  -> Hermes memory receives only compact durable facts
```

### 9.3 What Goes In Hermes Memory

Save:

- Stable user preferences.
- Stable project conventions.
- Durable company facts.
- Approved strategic decisions.
- Repeated operating lessons.
- Active constraints that affect future work.

Skip:

- Raw deliberation transcripts.
- Large board decisions.
- Temporary implementation details.
- Unapproved SOTB proposals.
- Facts that belong in source-controlled docs.

### 9.4 Memory Safety

Add these rules before using Hermes memory for business-critical continuity:

- No automatic promotion from board output to durable memory.
- All strategic memory writes require approval.
- Memory entries must be concise and source-linked to session IDs.
- Memory must include confidence or evidence level when relevant.
- Memory must be reversible through a visible edit history.

---

## 10. Board API Contract For Hermes

The current API returns the whole session dictionary. Long term, add a stable adapter schema.

### 10.1 Request

```json
{
  "query": "Should we activate the Security Guardian for this product?",
  "member_ids": null,
  "full_board": false,
  "verify": true,
  "context": {
    "source": "hermes",
    "decision_type": "role_evolution",
    "evidence_packet": "Optional compact evidence prepared by Hermes"
  }
}
```

### 10.2 Response

```json
{
  "session_id": "board_...",
  "classification": {
    "query_type": "full-board",
    "relevant_member_ids": ["strategist", "product", "critic", "chairperson"]
  },
  "decision": {
    "executive_summary": "...",
    "strategic_direction": "...",
    "next_steps": ["...", "...", "..."],
    "risk_register": ["..."],
    "dissenting_views": ["..."]
  },
  "verification": {
    "score": 8,
    "passed": true,
    "deficiencies": [],
    "suggestions": []
  },
  "memory": {
    "proposed_sotb_update": "...",
    "requires_approval": true
  },
  "artifacts": {
    "session_json_path": "data/sessions/board_....json"
  }
}
```

### 10.3 Required Code Changes Before Plugin Integration

- Persist verification results in `BoardSession`.
- Add a structured `decision` projection instead of requiring Hermes to parse Markdown.
- Return proposed SOTB updates without automatically applying them.
- Add stable error codes for board failures.
- Add auth or local-only enforcement before exposing API outside localhost.

---

## 11. Roster Evolution Architecture

The current loader already supports shelved members by filename prefix. That is a good simple
mechanism, but it is not enough for a growing business.

Add a roster registry:

```yaml
stage_profiles:
  pre_pmf:
    active: [chairperson, strategist, product, researcher, critic, architect, builder]
    optional: [guardian, operator]
  live_product:
    active: [chairperson, strategist, product, researcher, critic, architect, builder, guardian, operator]
  revenue:
    active: [chairperson, strategist, product, researcher, critic, architect, builder, guardian, operator, finance]

activation_rules:
  guardian:
    activate_when:
      - handles user data
      - uses external integrations
      - exposes public API
      - enters compliance scope
  operator:
    activate_when:
      - real users depend on uptime
      - release cadence exists
      - rollback/monitoring decisions recur
```

Hermes can propose changing the current stage profile. Human approval should be required.

---

## 12. Routing Architecture

The current classifier uses hardcoded query types and hardcoded member lists. That will not
scale as the business grows.

Replace:

```text
query_type -> hardcoded member IDs
```

With:

```text
query -> decision_type -> required capabilities -> member metadata -> selected roster
```

Member metadata should become functional:

```yaml
id: guardian
capabilities:
  - threat_modeling
  - data_privacy
  - compliance
activation:
  default_stage: live_product
  can_be_optional: true
cost:
  default_priority: 85
  invoke_on_high_impact_only: false
```

Hermes can help prepare routing context, but Agentic Board should remain responsible for final
member selection inside the board service.

---

## 13. Build Plan

### Installation Decision

Do not install `hermes-agent` as the first project step.

Install Hermes at the user/runtime level only after the board has a stable integration
contract:

```text
board contract fixed -> local Hermes skill draft -> install/configure Hermes -> invoke board
```

Do not add Hermes as a dependency in `pyproject.toml` yet. Keep Hermes optional until the
local skill proves that the workflow is valuable.

### Phase 0: Board Contract And Memory Gate

Before integrating Hermes:

- Persist verification results in session JSON.
- Stop automatically applying SOTB updates; return proposed updates instead.
- Add a minimal structured `decision` projection for board output.
- Add stable error codes for deliberation failure, verification failure, memory proposal
  parsing failure, and unavailable capability routing.
- Add tests for loader, classifier parsing, compaction extraction, SOTB update parsing,
  decision projection, and session serialization.
- Add local-only/auth safeguards before any non-local Hermes surface can call the API.
- Add security/operations routing or remove those output sections until those members are active.
- Document `.venv/bin/python` as a fallback if `uv` is unavailable.

Exit criteria:

- A board deliberation creates a session artifact with `decision`, `verification`, `metrics`,
  and `memory.proposed_sotb_update`.
- No durable SOTB or Hermes memory write occurs without human approval.

### Phase 1: C-Suite Roster Alignment

Make the board explicitly C-suite/governance-level before Hermes starts routing work to it.

Current active roster:

```text
chairperson, strategist, product, researcher, critic, architect, builder
```

Shelved members:

```text
guardian, operator
```

Target interpretation:

| Member | Governance Seat | Note |
|--------|-----------------|------|
| `chairperson` | CEO | Final synthesis and company direction |
| `strategist` | CSO | Market, evidence, competitive strategy |
| `product` | CPO | Product definition and PMF path |
| `researcher` | Acting CCO | Customer intelligence until a growth/revenue seat exists |
| `architect` | CTO | Architecture and technical feasibility |
| `critic` | Independent risk director | Dissent, pre-mortem, assumption challenge |
| `builder` | VP Engineering / execution feasibility | Transitional; may become Hermes operating skill later |
| `guardian` | CISO | Activate for data, auth, external integrations, public APIs, compliance |
| `operator` | COO / operations | Activate when real users depend on uptime and release process |
| `finance` | CFO | Add later when pricing, runway, margin, or fundraising recur |
| `legal` | CLO / counsel | Add later when contracts, regulated data, IP, or liability recur |

Add a roster registry with stage profiles:

```yaml
stage_profiles:
  pre_pmf:
    active: [chairperson, strategist, product, researcher, critic, architect, builder]
    optional: [guardian, operator]
  live_product:
    active: [chairperson, strategist, product, researcher, critic, architect, builder, guardian, operator]
  revenue:
    active: [chairperson, strategist, product, researcher, critic, architect, builder, guardian, operator, finance]
```

Exit criteria:

- The active board represents C-suite governance, not an implementation swarm.
- Shelved members have explicit activation rules.
- Any future board member requires a role-gap memo and benchmark query.

### Phase 2: Capability-Based Routing

Replace the current hardcoded query-type mapping with:

```text
query -> decision_type -> required_capabilities -> active_stage_profile -> selected_members
```

Routing layers:

1. Hermes intent router decides: direct response, operating skill, or board deliberation.
2. Agentic Board capability router selects members from active roster metadata.
3. Model router chooses model tier per step: cheap classifier, strong council models, strongest
   chair model, fast verifier.

Member metadata should include:

```yaml
id: guardian
capabilities:
  - threat_modeling
  - data_privacy
  - compliance
activation:
  default_stage: live_product
  can_be_optional: true
cost:
  default_priority: 85
  invoke_on_high_impact_only: false
```

Exit criteria:

- Classifier supports strategic, product, customer, technical, security, operational, finance,
  legal, and full-board decisions.
- If a required capability is unavailable, the system either falls back to the closest active
  member or produces a role-gap memo.

### Phase 3: Create Local Hermes Skill

Create:

```text
hermes/skills/agentic-board/SKILL.md
```

The skill should:

- Explain when to invoke the board.
- Prefer `--verify` for high-impact decisions.
- Capture session ID and summary.
- Present memory updates for approval.
- Avoid writing SOTB automatically.
- Use the CLI first; switch to the API only after the structured adapter exists.

Exit criteria:

- Hermes can invoke the board locally through CLI.
- The user can inspect the resulting board session.
- The board result is presented without mutating SOTB.

### Phase 4: Harden Board Decision Adapter

Harden the internal adapter so Hermes can rely on a stable contract instead of parsing
Markdown. The first version can extract from the chairman's structured Markdown output; the
longer-term version should make the chairman write the structured fields directly.

Exit criteria:

- Hermes receives structured fields: summary, next steps, risks, dissent, proposed memory.
- No brittle parsing is required in the Hermes skill.
- CLI and API responses expose the same adapter shape.
- The Hermes skill can switch from CLI output handling to the API/adapter contract if desired.

### Phase 5: Create Memory Review Skill

Create:

```text
hermes/skills/board-memory-update/SKILL.md
```

The skill should review SOTB proposals and produce a diff.

Exit criteria:

- Memory updates are reviewable before being applied.
- SOTB remains section-aware and under size limits.

### Phase 6: Add Role Evolution Skill

Create:

```text
hermes/skills/role-gap-review/SKILL.md
```

The skill should propose whether a repeated blind spot needs:

- no change,
- a new skill,
- an activated shelved member,
- a new board member.

Exit criteria:

- Board roster changes have a written rationale and benchmark query.

### Phase 7: Promote To Hermes Plugin

Only after the above works, create a plugin exposing:

```text
agentic_board_deliberate
agentic_board_list_members
agentic_board_read_sotb
agentic_board_propose_sotb_update
```

Exit criteria:

- Hermes can call Agentic Board through a typed tool contract.
- Memory writes still require approval.
- Plugin has tests and local-only/auth safeguards.

---

## 14. Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Hermes becomes the board instead of the operator | High | Keep board deliberation inside Agentic Board; expose it as a tool only |
| Skill sprawl creates fake evolution | High | Require three successful repeated uses before promoting a skill |
| Memory poisoning corrupts company direction | High | Human approval for strategic memory; source links to session IDs |
| Board roster grows too large | Medium | New members require role-gap memo and benchmark improvement |
| Markdown parsing breaks Hermes integration | Medium | Add structured adapter schema before plugin phase |
| API exposed unsafely | High | Keep localhost-only or add auth before network exposure |
| Session search treated as truth | Medium | Use search as evidence retrieval, not durable memory |
| Tool execution leaks into deliberation | Medium | Keep tools in Hermes pre-board evidence gathering and post-board execution |

---

## 15. Decision Rules

Use Agentic Board when:

- The decision is strategic, product-defining, risky, or cross-functional.
- You need dissent and explicit conflict resolution.
- The output should affect durable company memory.
- A prior board decision may constrain the answer.

Use Hermes without the board when:

- The task is procedural.
- A skill already covers the workflow.
- The user needs execution, not governance.
- The answer can be derived from existing memory and tools without a high-impact decision.

Create a Hermes skill when:

- A workflow repeats.
- It has clear triggers and boundaries.
- It improves consistency.
- It can be tested with examples.

Create or activate a board member when:

- A durable governance perspective is repeatedly missing.
- Existing members cannot cover it without scope creep.
- The business stage now requires that perspective.
- Benchmarks show better decisions with the new role.

---

## 16. Recommended Next Artifact

The next artifact should be the board integration contract, not the Hermes skill:

```text
server/board/schemas.py
server/board/memory_review.py
```

Start by defining the structured session/decision/memory proposal shape and stopping automatic
SOTB writes. The first Hermes artifact comes after that:

```text
hermes/skills/agentic-board/SKILL.md
```

That skill should be intentionally small. The first goal is not to make Hermes autonomous.
The first goal is to teach Hermes when to call the existing council service and how to handle
the result without corrupting memory.
