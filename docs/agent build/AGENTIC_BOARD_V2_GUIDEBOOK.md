# Agentic Board v2 Guidebook

> Current build guide for a company board that can evolve as the business grows.
> Updated on 2026-04-12 after reviewing the local project, Hermes Agent,
> gstack, llm-council, and the public Superpowers reference material.

---

## 0. Executive Thesis

Agentic Board should remain the governance service.

Hermes should be the operating runtime around it.

gstack and Superpowers should influence the process layer: skills, gates, reviews,
browser/tool discipline, and repeatable operating workflows.

llm-council should remain the deliberation pattern: independent responses,
anonymized peer review, and final chair synthesis.

The core boundary is:

```text
Hermes runtime
  -> gathers context, loads skills, searches memory, uses tools, executes workflows
  -> invokes Agentic Board only when a decision needs governance
  -> presents board decision, memory proposal, and next actions to the human

Agentic Board service
  -> classifies the decision
  -> selects active board members by capability and business stage
  -> runs the council deliberation protocol
  -> returns decision, dissent, risks, verification, and proposed memory updates

Human founder
  -> approves durable memory
  -> approves roster evolution
  -> approves high-impact execution
```

Do not make every repeatable workflow a board member. Most growth should happen
through Hermes skills. Add or activate board members only when the business has a
durable governance gap.

---

## 1. Source Basis

External sources reviewed:

- Hermes Agent: https://github.com/NousResearch/hermes-agent
- Hermes architecture: https://hermes-agent.nousresearch.com/docs/developer-guide/architecture
- Hermes tools: https://hermes-agent.nousresearch.com/docs/user-guide/features/tools
- Hermes skills: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- Hermes memory: https://hermes-agent.nousresearch.com/docs/user-guide/features/memory
- Hermes context compression: https://hermes-agent.nousresearch.com/docs/developer-guide/context-compression-and-caching
- gstack: https://github.com/garrytan/gstack
- gstack architecture: https://raw.githubusercontent.com/garrytan/gstack/main/ARCHITECTURE.md
- llm-council public docs: https://llm-council.dev/
- llm-council consensus ADR: https://llm-council.dev/adr/ADR-010-consensus-mechanisms/
- Superpowers public reference: https://github.com/obra/superpowers

Provenance note:

- The requested `ashapeng/llm-council` and `ashapeng/superpowers` GitHub URLs did
  not resolve through public browsing during this update. This guide uses the
  public llm-council docs and the public upstream Superpowers reference as the
  best available basis. If the private or forked `ashapeng` repositories contain
  project-specific changes, reconcile this guide against those forks later.

Local project files reviewed:

- `server/board/orchestrator.py`
- `server/board/classifier.py`
- `server/board/roster.py`
- `server/board/roster.yaml`
- `server/board/loader.py`
- `server/board/llm.py`
- `server/board/compaction.py`
- `server/board/schemas.py`
- `server/board/memory.py`
- `server/board/memory_review.py`
- `server/board/role_gap.py`
- `server/api.py`
- `server/cli.py`
- `server/members/*.md`
- `server/members/_guardian.md`
- `server/members/_operator.md`
- `server/memory/sotb.md`
- `hermes/README.md`
- `hermes/skills/agentic-board/SKILL.md`
- `hermes/skills/board-memory-update/SKILL.md`
- `hermes/skills/role-gap-review/SKILL.md`
- `hermes/plugins/agentic_board/*`
- `tests/test_board_contract.py`
- `tests/test_hermes_plugin.py`
- `tests/test_hermes_skill.py`
- `tests/test_roster_routing.py`

---

## 2. Current Project Diagnosis

### 2.1 What Is Already Built

The local project is no longer just a prompt collection. It has a real board
harness:

- Markdown board member files with YAML frontmatter in `server/members/*.md`.
- Shelved members in `_guardian.md` and `_operator.md`.
- A roster registry in `server/board/roster.yaml`.
- Business-stage profiles: `pre_pmf`, `live_product`, and `revenue`.
- Capability-based routing in `server/board/roster.py`.
- LLM classification in `server/board/classifier.py`.
- A three-stage council orchestrator in `server/board/orchestrator.py`.
- Optional Stage 4 verification in `server/board/verification.py`.
- System/user message separation in `server/board/llm.py`.
- Retry and fallback model behavior in `server/board/llm.py`.
- Pure parsing compaction in `server/board/compaction.py`.
- Session metrics in `server/board/metrics.py`.
- Structured adapter projection in `server/board/schemas.py`.
- Proposed memory updates rather than automatic SOTB writes.
- A local-only API guard in `server/api.py`.
- Hermes skills and a plugin scaffold under `hermes/`.

### 2.2 What The Board Currently Is

The current default profile is `pre_pmf`:

```text
chairperson, strategist, product, researcher, critic, architect, builder
```

This is the right shape for an early-stage company:

| Member | Governance Seat | Current Role |
|--------|-----------------|--------------|
| `chairperson` | CEO | Final synthesis and decision framing |
| `strategist` | CSO | Market strategy, competition, evidence |
| `product` | CPO | MVP scope, value proposition, PMF path |
| `researcher` | Acting CCO | Customer discovery and voice of customer |
| `critic` | Independent risk director | Premortem, dissent, assumption audit |
| `architect` | CTO | Technical feasibility and build-vs-buy |
| `builder` | VP Engineering / validation | Prototype plan and execution feasibility |

Shelved or later-stage seats:

| Member | Governance Seat | Activation Trigger |
|--------|-----------------|--------------------|
| `guardian` | CISO | User data, auth, public API, integrations, compliance |
| `operator` | COO | Live users, uptime, monitoring, release process |
| `finance` | CFO | Pricing, runway, margin, fundraising |
| `legal` | CLO / counsel | Contracts, regulated data, IP, liability |

Important current gap: `server/board/roster.yaml` mentions `finance` in the
`revenue` stage and includes `finance` and `legal` decision types, but there are
no `finance` or `legal` member files or member metadata yet. Treat those as
future placeholders until implemented.

### 2.3 What The Board Is Not

The board should not be:

- A general agent runtime.
- A task executor.
- A browser automation agent.
- A cron scheduler.
- A memory dump.
- A growing list of every specialist the company might ever need.

Those belong in Hermes skills, tools, session recall, and operating workflows.

---

## 3. Hermes Integration

### 3.1 Hermes Role

Hermes is a self-improving agent runtime with skills, memory, session search,
tools, gateways, cron jobs, terminal backends, and delegation. For this project,
Hermes is the operating layer around the board, not the replacement for the
board.

Use Hermes for:

- Loading operating skills.
- Gathering evidence before board meetings.
- Searching past sessions.
- Maintaining compact operating memory.
- Running terminal, file, browser, web, and automation tools.
- Converting approved board decisions into execution workflows.
- Proposing skill drafts after repeated workflows.

Do not use Hermes for:

- Re-implementing the internal council protocol.
- Silently changing board member prompts.
- Auto-writing SOTB memory.
- Letting tool execution leak into board deliberation.

### 3.2 Current Local Hermes Artifacts

This repo already keeps Hermes optional and source-controlled:

```text
hermes/
  README.md
  skills/
    agentic-board/SKILL.md
    board-memory-update/SKILL.md
    role-gap-review/SKILL.md
  plugins/
    agentic_board/
      README.md
      plugin.py
      schemas.py
```

`pyproject.toml` does not depend on Hermes. That is correct for now. Install and
configure Hermes at the user/runtime layer when ready.

### 3.3 Current Skill Boundary

`hermes/skills/agentic-board/SKILL.md` teaches Hermes when to invoke the board
and how to treat the session JSON as the integration contract.

The skill:

- Uses the local CLI.
- Prefers `--verify` for high-impact decisions.
- Reads `data/sessions/<session_id>.json`.
- Presents `decision`, `verification`, `classification`, and `memory` fields.
- Treats `memory.proposed_sotb_update` as a proposal only.
- Tells Hermes not to call `PUT /sotb` or write `server/memory/sotb.md` without
  explicit approval.

That is the right first integration path.

### 3.4 Current Plugin Boundary

The local plugin scaffold exposes intended tools:

```text
agentic_board_deliberate
agentic_board_list_members
agentic_board_read_sotb
agentic_board_propose_sotb_update
```

The plugin rejects non-local API targets. It does not expose a memory write
tool. `agentic_board_propose_sotb_update` calls `/sotb/review`, which returns a
diff and still requires human approval.

Promote this scaffold to a registered Hermes plugin only after the skill has
been used successfully for real board decisions.

### 3.5 Integration Rule

Use this progression:

```text
local CLI skill
  -> local API skill
  -> typed Hermes plugin
  -> remote/gateway use only after auth and approval gates
```

Do not skip directly to a plugin if the session contract, memory workflow, and
role-gap workflow are still changing.

---

## 4. llm-council Foundation

Agentic Board is structurally based on the llm-council pattern:

```text
Stage 1: multiple models/members answer independently
Stage 2: members review anonymized peer responses
Stage 3: chair model synthesizes the final answer
Stage 4: optional verifier reviews chair output
```

The local implementation maps that pattern to company governance:

- Members are not generic models; they are board seats with operating procedures.
- Stage 2 is anonymized to reduce authority and model bias.
- Stage 3 is identified so the chair can weigh domain expertise.
- Stage 4 checks whether the synthesis is actionable and faithful to dissent.
- Session JSON preserves the audit trail.

Future llm-council-inspired improvements:

- Add scoring/rubrics to Stage 2, not only prose review.
- Normalize reviewer scoring to reduce harsh/generous reviewer bias.
- Detect ties or unresolved disagreements explicitly.
- Track whether response length correlates with peer preference.
- Randomize peer response order to reduce position bias.
- Keep Borda or normalized scores as synthesis inputs, not as automatic final
  decisions.

The chair still decides. Voting can inform the decision; it should not replace
the chair's accountability.

---

## 5. gstack Lessons

gstack is relevant as a workflow system, not as a board replacement.

Key lessons to apply:

- Encode expertise as composable skills and commands.
- Run work in a practical sequence: think, plan, build, review, test, ship,
  reflect.
- Make each specialist feed the next step.
- Keep browser/tool state persistent when doing UI QA or live audits.
- Categorize commands by side effect and make errors actionable for agents.
- Validate generated skill documentation against source behavior to prevent doc
  drift.

How to apply this here:

```text
Board decision
  -> Hermes operating skill
  -> execution plan
  -> implementation
  -> review
  -> test / QA
  -> ship gate
  -> retrospective
  -> memory or skill update proposal
```

Do not copy gstack by making a CEO, designer, release manager, QA lead, and
security officer all permanent board participants. Those are operating roles
unless the business stage demands durable governance.

Practical gstack-derived rules for Agentic Board:

- Board members deliberate. Hermes skills operate.
- Browser and terminal tools stay outside board deliberation by default.
- UI/product QA can become a Hermes skill after the board approves a product
  direction.
- Shipping workflow belongs to `operator` only after the product has real users.
- Error messages in CLI/API/plugin flows should tell the agent the next action,
  not expose raw stack traces only.

---

## 6. Superpowers Evolution Model

Superpowers is useful as a discipline model: skills, hooks, planning, testing,
debugging, reviews, and systematic workflows instead of ad hoc prompting.

Apply that discipline to company growth:

- A workflow becomes a skill only after repeated successful use.
- A board member is added only after a repeated governance gap.
- Every promotion has a benchmark query.
- Every durable memory write has a review gate.
- Every roster change has a role-gap memo.
- Every plugin/tool promotion has tests.

### 6.1 Promotion Rules

Create a Hermes skill when:

- The workflow has occurred at least three times.
- The procedure is repeatable.
- "When to use" and "when not to use" are clear.
- The workflow is operational, not governance.
- The output can be verified with examples or tests.

Activate or create a board member when:

- A durable governance perspective is repeatedly missing.
- Existing board members cover it only by scope creep.
- The business stage now requires that perspective.
- A benchmark query shows better decisions with the role active.
- The added cost and latency are justified.

Keep as ad hoc prompting when:

- The task is one-off.
- The stakes are low.
- No memory or future workflow is affected.
- A direct answer is sufficient.

### 6.2 Hooks And Gates

Use Superpowers-style gates around the board:

| Gate | Trigger | Required Output |
|------|---------|-----------------|
| Decision gate | Hermes considers invoking board | One-sentence decision statement |
| Evidence gate | Board decision needs facts | Evidence packet with source quality |
| Verification gate | Chair synthesis produced | Score, deficiencies, pass/fail |
| Memory gate | SOTB update proposed | Diff, warnings, approval request |
| Role gate | Capability unavailable | Role-gap review and benchmark query |
| Skill gate | Workflow repeated | Skill draft with tests/examples |
| Plugin gate | Skill stable | Typed schema, tests, local-only/auth review |

---

## 7. Target Architecture

```text
Human founder
  |
  v
Hermes runtime
  - skills
  - tools/toolsets
  - compact memory
  - session search
  - cron/messaging
  - delegation
  |
  | board decision needed
  v
Agentic Board adapter
  - local CLI skill first
  - API adapter second
  - typed plugin later
  |
  v
Agentic Board service
  - roster/stage profile
  - classifier
  - markdown member loader
  - three-stage council
  - compaction
  - verification
  - memory proposal
  |
  v
Board artifacts
  - session JSON
  - structured decision projection
  - verification result
  - proposed SOTB update
  - metrics
  |
  | human approval
  v
Durable knowledge
  - SOTB
  - Hermes memory
  - approved Hermes skills
  - benchmark queries
```

---

## 8. Business-Stage Roster Guide

### 8.1 Stage: Pre-PMF

Use this stage while the company is still validating who the customer is and
what to build.

Active board:

```text
chairperson, strategist, product, researcher, critic, architect, builder
```

Do:

- Prioritize customer evidence and speed of learning.
- Prefer concierge, Wizard of Oz, landing page, or prototype validation.
- Keep security and operations represented by `architect`, `critic`, and
  `builder` unless the query specifically requires a shelved role.

Do not:

- Add Finance or Legal just because they exist in a mature-company org chart.
- Run the full board for every query.
- Turn implementation tasks into board decisions.

### 8.2 Stage: Live Product

Use this stage when real users depend on the product.

Activate:

```text
guardian, operator
```

Triggers:

- Public API.
- Auth or user accounts.
- Customer data storage.
- External integrations.
- Uptime expectations.
- Release process and rollback plans.
- Monitoring and incident response.

Expected active board:

```text
chairperson, strategist, product, researcher, critic, architect, builder, guardian, operator
```

### 8.3 Stage: Revenue

Use this stage when pricing, runway, margin, fundraising, contracts, IP, or
regulated data become recurring.

Add only after implementation:

```text
finance, legal
```

Required before activation:

- `server/members/finance.md` or `server/members/_finance.md`
- `server/members/legal.md` or `server/members/_legal.md`
- roster metadata in `server/board/roster.yaml`
- decision type capabilities wired to those roles
- role-gap memo and benchmark query
- tests proving routing selects the new member

Example benchmark queries:

- Finance: "Should we price per seat, per workflow, or usage-based for the
  first paid pilot?"
- Legal: "Can we use customer-uploaded documents in this workflow without
  creating unacceptable data retention or IP risk?"

### 8.4 Stage: Enterprise / Regulated

Do not create this stage until required.

Possible added seats:

- Compliance / privacy officer.
- Enterprise sales / revenue lead.
- Data governance lead.
- Support / customer success lead.

Each must pass the same role-gap and benchmark process.

---

## 9. Routing Model

The current system already uses:

```text
query -> classifier -> decision type -> required capabilities -> active stage profile -> selected members
```

Keep improving that model. Avoid going back to hardcoded member lists.

Desired decision types:

| Decision Type | Typical Capabilities |
|---------------|----------------------|
| `strategic` | market strategy, competitive analysis, evidence assessment |
| `product` | product strategy, MVP scope, PMF path |
| `customer` | interviews, JTBD, persona synthesis |
| `technical` | feasibility, architecture, build-vs-buy |
| `security` | threat modeling, privacy, compliance |
| `operational` | release readiness, monitoring, incident response |
| `finance` | pricing, runway, margin, fundraising |
| `legal` | contracts, IP, liability, regulated data |
| `full-board` | company direction or cross-domain risk |

Routing behavior:

- If a capability is active, select the owning member.
- If a capability is known but inactive, select the closest active members and
  emit a role-gap memo.
- If a capability is unknown, emit a role-gap memo and default to full-board or
  chair plus risk/strategy/product as appropriate.
- If classifier confidence is poor or parsing fails, fall back to full-board.

---

## 10. Memory Architecture

SOTB is not a transcript. It is the board's compact institutional memory.

Save only:

- Durable decisions.
- Active risks.
- Established positions.
- Open questions.
- Reversal conditions.
- Source session IDs.

Do not save:

- Raw deliberation.
- Temporary implementation details.
- Unapproved strategy changes.
- Large transcripts.
- Facts better stored in source-controlled docs.

### 10.1 Current State

The current `server/memory/sotb.md` is sectioned:

```text
Active Decisions
Risk Register
Established Positions
Open Questions
Last Session
```

`server/board/memory_review.py` can produce candidate SOTB text and a diff
without writing durable memory. This is the correct safety boundary.

### 10.2 Next Memory Upgrade

Make memory updates section-aware:

```markdown
## Active Decisions
- [date] [session_id]: Decision, rationale, owner, review date, reversal condition.

## Risk Register
- [risk_id]: Risk, probability, impact, mitigation, owner, status.

## Established Positions
- Position, evidence level, confidence, reversal condition.

## Open Questions
- Question, why it matters, evidence needed, owner.

## Last Session
- Session id, short summary, unresolved follow-up.
```

The chair should propose structured updates. The memory reviewer should produce
a section-aware diff. Hermes should present the diff. The human approves,
edits, or rejects it.

---

## 11. Board API And Adapter Contract

The stable integration surface is not the rich CLI text. It is the session JSON
and adapter projection.

Current useful fields:

```json
{
  "session_id": "board_...",
  "classification": {
    "query_type": "security",
    "complexity": "complex",
    "relevant_member_ids": ["chairperson", "critic", "architect"],
    "required_capabilities": ["threat_modeling", "data_privacy"],
    "unavailable_capabilities": ["threat_modeling"],
    "stage_profile": "pre_pmf",
    "role_gap_memo": "..."
  },
  "decision": {
    "executive_summary": "...",
    "critical_findings": ["..."],
    "strategic_direction": "...",
    "architecture_design": "...",
    "security_posture": "...",
    "implementation_plan": ["..."],
    "risk_register": ["..."],
    "dissenting_views": ["..."],
    "next_steps": ["..."]
  },
  "verification": {
    "score": 8,
    "passed": true,
    "deficiencies": [],
    "suggestions": []
  },
  "memory": {
    "proposed_sotb_update": "...",
    "requires_approval": true,
    "source": "session:board_..."
  },
  "metrics": {}
}
```

Adapter rules:

- Use `/sessions/{session_id}/adapter` when consuming saved sessions through the API.
- Keep `/sotb/review` as a proposal endpoint.
- Keep `PUT /sotb` manual and explicit.
- Keep API local-only by default unless auth is added.
- Do not expose the board API over a messaging gateway without approval and auth.

---

## 12. Implementation Design By Phase

This section maps the original phase plans in `docs/impl_plans/` to a lean
implementation design. Many phases are already structurally implemented in the
current repo; treat this as the build and hardening guide, not permission to
rewrite working modules.

Design rule for every phase:

```text
Prefer one small file, one stable contract, and one verification path.
Do not add a framework until repeated use proves the simple version is failing.
```

### Phase 0: Output Format And Member Template

Goal: define the contracts before adding intelligence.

Lean implementation:

- Keep `server/protocols/output_format.md` as the member response contract.
- Keep `server/members/_template.md` as the member prompt contract.
- Keep stage wrappers in `server/protocols/stage1_independent.md`,
  `server/protocols/stage2_peer_review.md`, and
  `server/protocols/stage3_synthesis.md`.
- Make each protocol file short enough that a human can audit it in one pass.
- Require only the sections that downstream code actually consumes:
  confidence, TL;DR, recommendation, risks, updated position, peer challenges,
  ranking, and chair decision sections.

Do not build:

- A prompt registry database.
- A prompt versioning service.
- LLM-generated protocol files.
- Complex schema validation for Markdown before live output proves it is needed.

Exit criteria:

- Protocol files and member template exist.
- Output format headings match what `server/board/compaction.py` and
  `server/board/schemas.py` parse.
- A human can add a new member by copying `_template.md`.

### Phase 1: Infrastructure

Goal: make the board harness reliable without changing board behavior.

Lean implementation:

- Use `server/board/loader.py` to parse Markdown files with YAML frontmatter.
- Keep `BoardMember` in `server/board/config.py` as a small dataclass.
- Use `server/board/llm.py` as the only provider client.
- Send member prompts as system messages and stage prompts as user messages.
- Return `LLMResponse` with content, actual model, token counts, and latency.
- Track metrics in `server/board/metrics.py`.
- Keep retry and fallback logic simple:
  - 3 primary attempts.
  - 1 configured fallback model.
  - no circuit breaker unless repeated live failures justify it.

Do not build:

- Provider abstraction layers.
- Per-model tuning tables beyond the few env-configured defaults.
- A telemetry service.
- Durable metrics storage before there are enough live sessions to analyze.

Exit criteria:

- Members load from Markdown.
- LLM calls use system/user separation.
- Token/cost metrics appear in session JSON and CLI budget output.
- A failed provider call retries and then falls back or surfaces a clear error.

### Phase 2: First Member

Goal: validate one member before scaling the pattern.

Lean implementation:

- Treat `server/members/strategist.md` as the reference member.
- Keep the prompt procedural: identity, core question, 3-5 operating procedures,
  domain boundaries, anti-patterns, evidence standards, Stage 2 behavior.
- Evaluate on three fixed benchmark questions before editing other members.
- Tighten only the observed failure:
  - bad format -> strengthen output instruction.
  - weak evidence -> strengthen evidence standard.
  - scope creep -> strengthen domain boundaries.
  - overconfidence -> strengthen confidence calibration.

Do not build:

- Automated prompt optimization.
- A/B testing infrastructure.
- More member files before the first member output is readable.

Exit criteria:

- The Strategist follows the output format.
- It classifies evidence instead of inventing certainty.
- It avoids technical implementation advice unless the query truly requires it.
- Token metrics are captured for the test runs.

### Phase 3: Full Council

Goal: create a small board with differentiated seats.

Lean implementation:

- Keep the default `pre_pmf` board at seven seats:
  `chairperson`, `strategist`, `product`, `researcher`, `critic`,
  `architect`, and `builder`.
- Keep `guardian` and `operator` shelved behind `_guardian.md` and
  `_operator.md` until the stage profile activates them.
- Use member files as the prompt source of truth.
- Use `server/board/roster.yaml` as the capability and stage source of truth.
- Keep domain boundaries explicit enough that members defer instead of echoing.

Do not build:

- Direct agent-to-agent communication.
- More permanent seats for one-off blind spots.
- A board graph or multi-round debate system.
- Finance or Legal until role-gap signals justify them and member files exist.

Exit criteria:

- Full deliberation runs end to end.
- Stage 1 responses are differentiated by seat.
- Stage 2 challenges are substantive, not praise.
- The chair produces a decision, not a transcript summary.

### Phase 4: Context Compaction

Goal: reduce token load without hiding the decision signal.

Lean implementation:

- Keep compaction in `server/board/compaction.py`.
- Start with pure parsing, not another LLM call.
- Stage 1 to Stage 2 should preserve:
  - confidence,
  - TL;DR,
  - recommendation,
  - top risk.
- Stage 2 to Stage 3 should preserve:
  - confidence,
  - updated position,
  - peer challenges,
  - ranking.
- Keep raw responses in session JSON for audit.

Do not build:

- Vector retrieval for a single deliberation.
- LLM summarization by default.
- Multi-level compression pipelines.
- Lossy deletion of raw session artifacts.

Upgrade trigger:

- If live sessions show critical dissent is dropped, add fuzzy heading matching
  first. Use an LLM compactor only for high-impact full-board sessions.

Exit criteria:

- Stage 2 and Stage 3 receive compacted inputs.
- Raw responses remain available in saved sessions.
- Token usage drops measurably.
- Chair synthesis quality does not degrade in live review.

### Phase 5: Adaptive Routing

Goal: invoke the smallest board that can make the decision well.

Lean implementation:

- Keep the LLM classifier in `server/board/classifier.py`.
- Keep deterministic capability selection in `server/board/roster.py`.
- Route through:

```text
query -> decision_type -> capabilities -> active stage profile -> members
```

- Always include the chair.
- Prefer active members.
- If a capability is unavailable, return `classification.role_gap_memo` instead
  of silently pretending the board has that expertise.
- Keep manual overrides in the CLI:
  - `--members`
  - `--full-board`

Do not build:

- A separate routing service.
- Embedding search over member prompts.
- Dynamic prompt synthesis for routing.
- Auto-activation of shelved members without a stage/profile decision.

Exit criteria:

- Ten benchmark queries route sensibly at least 8 times.
- Focused queries cost less than full-board queries.
- Unavailable capabilities are visible in the session contract.

### Phase 6: Institutional Memory

Goal: make board memory durable but hard to corrupt.

Lean implementation:

- Keep `server/memory/sotb.md` as the board memory file.
- Keep SOTB compact and sectioned:
  Active Decisions, Risk Register, Established Positions, Open Questions,
  Last Session.
- Keep `server/board/memory.py` responsible for reading and extracting proposed
  updates.
- Keep `server/board/memory_review.py` responsible for candidate diffs.
- Store proposed updates in session JSON.
- Require explicit human approval before writing durable SOTB changes.

Do not build:

- Automatic memory writes from chair output.
- A vector database for board memory.
- Session transcript promotion into memory.
- Word-count truncation that can break Markdown structure.

Next minimal upgrade:

- Make SOTB updates section-aware:
  - append or edit one section at a time,
  - preserve unrelated sections,
  - attach session IDs,
  - avoid arbitrary truncation.

Exit criteria:

- Session output includes `memory.proposed_sotb_update`.
- `/sotb/review` returns a diff without writing.
- SOTB updates are approval-gated.
- Later sessions can use approved decisions without relitigating them.

### Phase 7: Verification Layer

Goal: catch weak chair synthesis before the user treats it as board judgment.

Lean implementation:

- Keep verification in `server/board/verification.py`.
- Use a separate model from the chair.
- Return a small `VerificationResult`:
  score, passed, deficiencies, suggestions.
- Keep verification opt-in with `--verify`.
- Allow at most one chair revision if verification fails.

Do not build:

- Multi-evaluator panels.
- Rubric dashboards.
- Continuous self-critique loops.
- Automatic rejection of board decisions without showing the human why.

Exit criteria:

- Verification result is saved in session JSON.
- Failed verification triggers one revision.
- The user can see deficiencies instead of trusting a hidden score.
- Five live runs show whether the verifier catches real issues or merely rubber
  stamps.

### Phase 8: Error Handling And Resilience

Goal: degrade gracefully when a model or member call fails.

Lean implementation:

- Use `asyncio.gather(..., return_exceptions=True)` in stage calls.
- Log member failures and continue when thresholds are met.
- Enforce minimum response thresholds:
  - Stage 1: at least 3 responses.
  - Stage 2: at least 2 responses.
- Keep fallback models in a simple dict in `server/board/llm.py`.
- Surface failures in CLI/API progress events.
- Save successful session artifacts even when non-critical members fail.

Do not build:

- Distributed queues.
- Circuit breakers with persistent state.
- Per-provider health dashboards.
- Automatic re-routing to unrelated members after a role fails.

Exit criteria:

- One or two failed member calls do not kill a deliberation.
- Too few successful responses abort with `BoardDeliberationError`.
- API errors use stable error codes.
- CLI output makes the failure understandable.

### Phase 9: CLI, API, And Polish

Goal: make the working board usable without widening the trust boundary.

Lean implementation:

- Keep `server/cli.py` as the primary human operator surface.
- Keep useful CLI flags:
  `--interactive`, `--list-members`, `--verbose`, `--members`,
  `--full-board`, `--verify`, `--budget`, and `--json`.
- Keep `server/api.py` local-only by default.
- Expose only necessary API routes:
  - `/members`
  - `/deliberate`
  - `/deliberate/stream`
  - `/sessions`
  - `/sessions/{session_id}`
  - `/sessions/{session_id}/adapter`
  - `/sotb`
  - `/sotb/review`
  - `/role-gap/review`
  - `/metrics/summary`
- Use `server/board/schemas.py` for stable adapter projection.

Do not build:

- Remote API exposure without auth.
- A production dashboard.
- A database migration from JSON sessions.
- A registered Hermes plugin before the skill path is stable.

Exit criteria:

- CLI and API expose the same core session contract.
- Local tests pass.
- Hermes skill can consume the session JSON or adapter endpoint.
- Memory writes remain explicit and approval-gated.

### Phase 10: Business Growth Extensions

Goal: evolve the board only when the company changes.

Lean implementation:

- Use `hermes/skills/role-gap-review/SKILL.md` when missing capabilities recur.
- Activate `guardian` and `operator` through stage profiles before creating new
  seats.
- Add Finance or Legal only after:
  - repeated role-gap signals,
  - a written role-gap memo,
  - a member file,
  - roster metadata,
  - benchmark queries,
  - routing tests,
  - live comparison with and without the role.
- Promote `hermes/plugins/agentic_board/` only after the CLI/API skill flow is
  stable.

Do not build:

- A mature-company org chart in advance.
- Permanent board members for temporary operating work.
- Remote Hermes gateway access before auth and approval gates.
- Memory write tools in the plugin.

Exit criteria:

- Every new skill or board member has evidence of repeated need.
- The board remains small enough for real dissent and affordable deliberation.
- Governance, operation, memory, and execution remain separate.

---

## 13. Operating Decision Rules

Use direct response when:

- The question is factual, low stakes, or one-off.
- No durable company memory should change.
- No dissent or tradeoff resolution is required.

Use a Hermes skill when:

- The work is procedural.
- The workflow has clear steps.
- The output can be verified.
- The decision has already been made or does not require board governance.

Use Agentic Board when:

- The decision is strategic, product-defining, risky, or cross-functional.
- The output may change durable company memory.
- Dissent matters.
- A prior board decision may constrain the answer.
- A missing capability or stage transition may be involved.

Use full board when:

- The decision affects company direction.
- The query spans market, product, customer, technical, and risk domains.
- The classifier is uncertain.
- The user explicitly asks for full-board deliberation.

Use role-gap review when:

- `classification.unavailable_capabilities` is non-empty.
- The same missing capability appears in two or more sessions.
- A shelved member could cover the gap.
- The user asks whether to activate or create a board role.

---

## 14. Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Hermes becomes the board | High | Keep council protocol inside Agentic Board; expose it as a tool only |
| Board roster grows by enthusiasm | High | Require role-gap memo, benchmark query, and repeated need |
| Memory poisoning | High | Human approval for all durable strategic memory |
| Finance/legal placeholder causes routing confusion | Medium | Do not activate until member files and metadata exist |
| Compaction drops critical dissent | High | Run live evaluations; add fuzzy parsing or high-impact LLM compaction if needed |
| API exposure | High | Keep local-only default; add auth before any remote gateway |
| Session search treated as truth | Medium | Use Hermes recall as evidence retrieval, not durable memory |
| Tool use leaks into deliberation | Medium | Tools gather evidence before board and execute after approval |
| Verification score inflates | Medium | Review verifier output across live runs and tune rubric |
| Skills drift from project behavior | Medium | Add tests or generated sections for skill commands before broad use |

---

## 15. Immediate Next Steps

1. Run the local unit tests.
2. Run five live board benchmark sessions.
3. Inspect classification, Stage 2 challenge quality, chair synthesis, verification,
   cost, and proposed memory.
4. Fix compaction only if benchmark output shows real signal loss.
5. Upgrade SOTB to section-aware diffs.
6. Use the Hermes CLI skill for several real decisions.
7. Promote the plugin only after the skill path stops changing.

---

## Appendix A: Current File Map

```text
server/
  api.py                         # FastAPI, local-only by default
  cli.py                         # Rich CLI and JSON output
  board/
    orchestrator.py              # 3-stage board plus optional verifier
    classifier.py                # LLM query classification
    roster.py                    # capability/stage profile selection
    roster.yaml                  # stage profiles and member capabilities
    loader.py                    # markdown member loader
    llm.py                       # OpenRouter client, retries, fallbacks
    compaction.py                # parser-based inter-stage compaction
    verification.py              # synthesis quality gate
    schemas.py                   # stable adapter projections
    memory.py                    # SOTB read/extract/apply helpers
    memory_review.py             # proposed SOTB diff, no durable write
    role_gap.py                  # skill vs shelved member vs new member review
  members/
    chairperson.md
    strategist.md
    product.md
    researcher.md
    critic.md
    architect.md
    builder.md
    _guardian.md
    _operator.md
    _template.md
  memory/
    sotb.md

hermes/
  README.md
  skills/
    agentic-board/SKILL.md
    board-memory-update/SKILL.md
    role-gap-review/SKILL.md
  plugins/
    agentic_board/
      README.md
      plugin.py
      schemas.py

tests/
  test_board_contract.py
  test_hermes_plugin.py
  test_hermes_skill.py
  test_roster_routing.py
```

## Appendix B: North Star

The board should get more useful as the company grows, but not by getting
bigger by default.

The growth path is:

```text
better evidence -> better routing -> better board decisions
  -> approved memory -> repeatable Hermes skills
  -> evaluated operating workflows -> role-gap signals
  -> selective board evolution
```

That keeps governance, operations, memory, and execution separate enough to
scale without turning the board into an expensive swarm.
