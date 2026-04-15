# Harness Engineering for Agentic Board Teams

## A Critical Guide to Multi-Agent Design for This Project

This guide replaces the generic "agent team" framing with a project-specific
one. Agentic Board is a governance product for a solo company. It should help
the founder make better high-leverage decisions, preserve institutional memory,
surface dissent, and return auditable recommendations. It should not become a
general-purpose autonomous execution swarm.

The core design boundary is:

```text
Hermes runtime
  -> gathers evidence, loads skills, searches sessions, uses tools, executes work
  -> invokes Agentic Board only when a governance decision is needed
  -> presents the board decision, risks, dissent, memory proposal, and next steps

Agentic Board service
  -> classifies the decision
  -> selects board members by capability and business stage
  -> runs independent analysis, anonymized peer review, and chair synthesis
  -> verifies decision quality when requested
  -> proposes durable memory updates without applying them automatically

Human founder
  -> approves durable memory
  -> approves roster evolution
  -> approves high-impact execution
```

---

## 1. Critical Assessment of the Previous Agent-Team Framing

The previous guide correctly emphasized several useful harness principles:

- The model is the agent; code is the harness.
- Context isolation between agents is essential.
- State that matters should live outside the conversation.
- Subagent results should be summarized before returning to the parent.
- Parallelism should be measured by critical path, not by number of spawned agents.
- Worktree isolation is useful when multiple coding agents edit the same repo.

Those ideas are valid, but the guide was too generic for this product. It mixed
three different systems:

- a governance council that deliberates
- an operating runtime that executes work
- a coding-agent team that changes files

That mix creates product risk. It can push Agentic Board toward persistent
teammates, inboxes, self-claiming task boards, worktree lanes, and learned
parallel orchestration when the current product needs a smaller, more reliable
governance service.

The corrective principle:

```text
Use agent-team machinery where it belongs.
Do not put execution-team machinery inside the board deliberation service.
```

---

## 2. The Three Team Planes

### Plane 1: Governance Team

This is Agentic Board itself.

Current code shape:

- `server/board/orchestrator.py`
- `server/board/classifier.py`
- `server/board/roster.py`
- `server/board/roster.yaml`
- `server/board/compaction.py`
- `server/board/verification.py`
- `server/board/schemas.py`
- `server/board/memory_review.py`
- `server/members/*.md`
- `server/protocols/*.md`
- `server/memory/sotb.md`

Design:

```text
Decision packet
  -> classifier
  -> capability and stage routing
  -> Stage 1: independent board member analysis
  -> Stage 2: anonymized peer review
  -> Stage 3: chair synthesis
  -> Stage 4: optional verification and one revision
  -> decision record + memory proposal + metrics
```

The board members are durable governance seats, not autonomous workers. They do
not need direct mailboxes, filesystem write access, worktree lanes, or idle
polling. Their job is to deliberate and produce decision signal.

### Plane 2: Operating Team

This is Hermes and its skills, tools, memory, session search, gateways,
delegation, and future plugins.

Use Hermes for:

- gathering evidence before a board meeting
- turning an approved decision into an execution plan
- running repeatable workflows
- maintaining compact operating memory
- proposing new skills after repeated workflows
- presenting SOTB diffs for human approval
- invoking terminal, browser, file, API, and automation tools

Hermes may use subagents, task boards, and execution queues. Those belong around
the board, not inside the board service.

### Plane 3: Implementation Team

This is where coding agents build or modify the repository.

Use implementation-team mechanics for:

- parallel coding tasks with disjoint write scopes
- worktree isolation
- review agents
- QA agents
- migration and release work
- long-running refactors

This plane can borrow from Claude Code-style task boards and worktrees. It
should produce code changes, tests, and docs. It should not silently change
board memory, roster activation, or member prompts without the same review gates
the product requires.

---

## 3. Product-Specific Team Architecture

### 3.1 Governance Team Architecture

Agentic Board already has the right base topology:

```text
                    +------------------+
                    |  decision packet |
                    +---------+--------+
                              |
                              v
                    +------------------+
                    |    classifier    |
                    +---------+--------+
                              |
                              v
                    +------------------+
                    | roster / profile |
                    +---------+--------+
                              |
                              v
       +----------------------+----------------------+
       |                      |                      |
       v                      v                      v
  strategist              product                researcher
       |                      |                      |
       +----------------------+----------------------+
                              |
                              v
                    Stage 1 compacted responses
                              |
                              v
                    Stage 2 anonymized challenge
                              |
                              v
                    Chairperson synthesis
                              |
                              v
                    Optional verifier
                              |
                              v
                    Decision record
```

This is not a worker pool. It is a staged deliberation protocol. The team value
comes from role diversity, independence, structured challenge, and chair
accountability.

### 3.2 Active Seats by Business Stage

The current default stage is `pre_pmf`, which is correct for this project:

```text
chairperson, strategist, product, researcher, critic, architect, builder
```

This stage should bias toward:

- market evidence
- customer pain
- MVP scope
- speed of validation
- technical feasibility
- assumption risk
- prototype path

Shelved or later-stage seats:

- `guardian`: activate when user data, auth, public APIs, integrations,
  compliance, or attack surface become recurring governance concerns.
- `operator`: activate when live users depend on uptime, release process,
  monitoring, rollback, or incident response.
- `finance` and `legal`: keep as future placeholders until member files, roster
  metadata, benchmark queries, and role-gap evidence exist.

### 3.3 Routing Is the Coordination Backbone

For this product, the coordination backbone is not a `.tasks/` directory. It is:

```text
query -> classifier -> decision type -> required capabilities
      -> active stage profile -> selected board members
```

Improve that path before adding team machinery. Good routing gives the founder
the smallest useful council. Bad routing creates cost, latency, weak dissent,
and member echo.

Routing should surface:

- selected member IDs
- required capabilities
- unavailable capabilities
- stage profile
- role-gap memo
- classifier confidence or fallback reason

These fields belong in the session JSON and adapter projection so Hermes and the
UI can explain why the board was assembled.

---

## 4. Agent-Team Patterns to Keep

### 4.1 Independent Parallel Analysis

Keep Stage 1 independent. It is the board equivalent of context isolation.

Required properties:

- each selected member receives the decision packet independently
- no member sees another Stage 1 answer
- member identity and operating procedure are explicit
- output format is stable enough for compaction and schema projection
- errors are recorded per member without poisoning other member contexts

### 4.2 Anonymized Peer Review

Keep Stage 2 anonymized. It reduces authority bias and forces members to engage
with claims rather than personalities.

Stage 2 should require:

- strongest challenge
- strongest agreement
- material change in position, if any
- ranking or prioritization of peer claims
- explicit unresolved disagreement

Weak Stage 2 output is usually a protocol problem, not a reason to add more
members.

### 4.3 Chair Synthesis

The chair should decide, not summarize.

The synthesis must include:

- final recommendation
- conflict resolution
- dissenting views
- assumptions
- risks and reversal conditions
- next actions
- memory proposal

Voting or scoring can inform the chair. It should not replace chair
accountability.

### 4.4 Verification as a Separate Role

Stage 4 should remain a verifier pass, not another board debate.

The verifier should check:

- the decision answers the question
- the chair used the right evidence
- dissent was preserved
- next steps are actionable
- SOTB proposals are separate from approved memory
- no unsupported certainty was introduced

If verification fails, allow at most one chair revision before returning a
"needs review" result.

### 4.5 Role-Gap Review

When routing identifies missing capability, do not immediately create a member.
Run a role-gap review.

Role-gap review should ask:

- Is the capability truly missing, or just inactive?
- Can an existing active member cover it for now?
- Is the gap recurring enough to justify a durable seat?
- What benchmark query proves the new role improves decisions?
- What cost and latency does the new role add?

---

## 5. Agent-Team Patterns to Avoid Inside Agentic Board

### Avoid Persistent Worker Teammates

Do not put long-lived coding-style teammates inside the board service. Board
members should not idle, poll for work, self-claim tasks, or maintain private
mailboxes. That would turn governance into operations.

### Avoid Direct Member-to-Member Messaging

Direct messages between board members undermine the staged deliberation design.
The board needs independent Stage 1 analysis and controlled Stage 2 challenge,
not informal negotiation.

### Avoid Worktrees in the Board Runtime

Worktrees are useful for implementation agents that edit files. Board members
do not need isolated Git directories to deliberate. Keep worktree mechanics in
the implementation plane.

### Avoid Swarm Parallelism as Product Theater

Spawning many agents is not automatically better. The board should optimize for
decision quality per cost and latency, not visible parallel activity.

### Avoid Role Inflation

Do not add permanent board seats for every workflow. Most specialists should be
Hermes skills or ad hoc evidence-gathering workflows. Add a board seat only for
durable governance perspective.

---

## 6. Where Task Boards and Worktrees Belong

Task boards and worktrees are still valuable, but they belong downstream of a
board decision.

Recommended flow:

```text
Board decision
  -> Hermes converts approved next actions into execution tasks
  -> implementation agents claim scoped tasks
  -> worktrees isolate code changes
  -> tests and review gates verify work
  -> Hermes proposes retrospective memory or skill updates
  -> founder approves durable changes
```

Use a task board when:

- work has multiple implementation steps
- dependencies need explicit ordering
- multiple coding agents can work in parallel
- progress must survive context compaction or agent restart

Use worktrees when:

- two agents may edit overlapping repo areas
- changes need separate branches
- a task may take long enough to block other work
- review should happen before merge

Do not use task boards just to make a single board deliberation look more
agentic. The current council protocol is already the right board-level task
structure.

---

## 7. Contracts for This Project

### 7.1 Decision Packet

The decision packet is the input contract:

```json
{
  "question": "What should the board decide?",
  "business_stage": "pre_pmf",
  "decision_type": "product",
  "context": "Relevant facts and evidence.",
  "constraints": ["budget", "deadline", "non-goal"],
  "options": ["A", "B", "C"],
  "requested_output": "decision record",
  "memory_context": "approved SOTB excerpts"
}
```

The product should move toward making this explicit in UI, CLI, and Hermes
adapter flows.

### 7.2 Member Response

Member responses should remain procedural and parseable:

- confidence
- TL;DR
- recommendation
- reasoning
- evidence and assumptions
- risks
- handoff to other seats

Every member file in `server/members/*.md` should preserve domain boundaries.
When a member starts answering outside its domain, tighten the prompt or routing
instead of letting all members become generalists.

### 7.3 Peer Review Delta

Stage 2 should output deltas, not restated essays:

- challenge one or more specific peer claims
- agree with the strongest evidence
- revise position if warranted
- identify unresolved disagreement
- rank what the chair should weigh most

This keeps chair context compact and decision-relevant.

### 7.4 Decision Record

The decision record is the output contract:

```json
{
  "decision": {
    "executive_summary": "...",
    "strategic_direction": "...",
    "architecture_design": "...",
    "risk_register": ["..."],
    "dissenting_views": ["..."],
    "next_steps": ["..."]
  },
  "classification": {
    "query_type": "product",
    "relevant_member_ids": ["chairperson", "product", "researcher", "critic"],
    "unavailable_capabilities": []
  },
  "verification": {
    "score": 8,
    "passed": true,
    "deficiencies": []
  },
  "memory": {
    "proposed_sotb_update": "...",
    "requires_approval": true
  },
  "metrics": {}
}
```

The UI and Hermes plugin should rely on this projection rather than raw chair
memo parsing.

---

## 8. Implementation Roadmap

### Phase 1: Harden the Existing Governance Team

Do this before adding autonomous team infrastructure:

- Keep the `pre_pmf` roster small and stage-driven.
- Improve classifier explanations and role-gap memos.
- Ensure unavailable capabilities are visible in adapter output.
- Strengthen Stage 2 delta requirements if peer review becomes vague.
- Keep the chair decision record structured and adapter-friendly.
- Expand Stage 4 verification only when it catches observed failures.

Exit criteria:

- A founder can see who was invited, why, what they disagreed about, and what the
  chair decided.
- SOTB updates are proposed, diffed, and require approval.
- Session JSON contains routing, decision, verification, memory, and metrics.

### Phase 2: Strengthen Hermes as the Operating Layer

Do this outside the board service:

- Use the `agentic-board` skill for local CLI invocation.
- Promote to local API usage only after the session contract is stable.
- Promote to typed plugin only after repeated real use.
- Add evidence-gathering skills before board invocation.
- Add execution skills after approved decisions.

Exit criteria:

- Hermes can prepare a decision packet.
- Hermes can invoke the board.
- Hermes can present the decision record and SOTB proposal.
- Hermes cannot silently write durable board memory.

### Phase 3: Add Execution Task Boards Only After Decisions

Use task boards for post-decision implementation, not board deliberation.

Minimum task fields:

```json
{
  "id": "task-001",
  "source_session_id": "board_...",
  "decision_link": "short summary",
  "status": "pending",
  "owner": "",
  "blocked_by": [],
  "acceptance_criteria": [],
  "write_scope": []
}
```

Exit criteria:

- Tasks trace back to an approved board decision or direct founder instruction.
- Every task has acceptance criteria and write scope.
- Completion requires tests, review, or an explicit verification artifact.

### Phase 4: Use Worktrees for Coding-Agent Parallelism

Only use worktrees when multiple implementation agents need isolation.

Rules:

- one task per worktree
- one branch per worktree
- explicit write scope
- no direct SOTB writes
- no member prompt edits without review
- tests must run before merge

Exit criteria:

- Parallel implementation does not create file collisions.
- Review can inspect each task independently.
- Board governance artifacts remain protected.

---

## 9. Decision Framework

### Use Agentic Board When

- A decision affects company direction.
- There is meaningful uncertainty or cross-domain risk.
- Dissent would improve the outcome.
- A durable memory update may be needed.
- The founder needs an auditable recommendation.

Examples:

- "Which customer segment should we validate first?"
- "Should we activate Guardian before launching this integration?"
- "Should this become a Hermes skill or remain ad hoc?"

### Use Hermes Without the Board When

- The task is operational and follows an existing decision.
- The workflow is repeatable.
- Tools, files, browser, APIs, or terminal execution are needed.
- The output is an execution artifact rather than a governance decision.

Examples:

- "Gather five customer interview notes into an evidence packet."
- "Run the board-memory-update skill and present the diff."
- "Convert approved next steps into implementation tasks."

### Use Implementation Agents When

- Code, tests, docs, or UI need to change.
- Work can be scoped by file or module.
- Verification can be automated.
- Parallelism reduces wall-clock time without increasing merge risk.

Examples:

- "Add adapter fields for unavailable capabilities."
- "Write tests for role-gap routing."
- "Build the UI panel for memory approval."

---

## 10. Operating Metrics

Track governance quality, not just agent activity.

Board metrics:

- selected members per session
- unavailable capabilities per session
- Stage 1 failure rate
- Stage 2 challenge specificity
- verification score and failure reasons
- chair revision rate
- token and cost per stage
- memory proposal approval/rejection rate
- role-gap recurrence

Hermes metrics:

- board invocations by skill or plugin
- evidence packets prepared
- SOTB diffs proposed
- approved decisions converted into tasks
- workflow repetitions that should become skills

Implementation-team metrics:

- tasks completed per decision
- review failures
- test failures
- merge conflicts
- worktree lifetime
- rollback or rework rate

---

## 11. Anti-Patterns

### Board as Worker Pool

Symptom: members claim tasks, run tools, and execute work.

Fix: move execution into Hermes or implementation agents.

### Every Specialist Becomes a Board Seat

Symptom: the roster grows whenever a new workflow appears.

Fix: create Hermes skills for workflows; add board seats only for repeated
governance gaps.

### Full Board for Everything

Symptom: every query invokes all members.

Fix: improve classifier, decision types, capabilities, and stage profiles.

### Chair as Summarizer

Symptom: the final memo restates member opinions without deciding.

Fix: strengthen chair protocol and verifier rubric around conflict resolution.

### Memory Auto-Write

Symptom: a session changes SOTB without human approval.

Fix: keep memory proposal and approved memory separate. Require a diff and an
explicit approval gate.

### Parallelism Theater

Symptom: many agents are spawned but decision quality does not improve.

Fix: measure critical path, cost, verification score, and approval outcomes.

---

## 12. Key Principles

1. Agentic Board is the governance team, not the execution team.

2. Hermes is the operating runtime around the board.

3. Coding-agent teams and worktrees belong in the implementation plane.

4. Routing is the board's coordination backbone.

5. Stage 1 independence and Stage 2 anonymized challenge are the core
   multi-agent mechanisms.

6. The chair decides. The verifier checks. The human approves durable changes.

7. Add roles only after role-gap evidence, benchmark queries, and explicit
   activation criteria.

8. Improve contracts, routing, protocols, schemas, metrics, and approval gates
   before adding more agents.

---

## 13. Local Source Basis

This guide is aligned with the current project files:

- `CLAUDE.md`
- `docs/AGENTIC_BOARD_V2_GUIDEBOOK.md`
- `docs/agent build/harness_engineering.md`
- `server/board/orchestrator.py`
- `server/board/classifier.py`
- `server/board/roster.py`
- `server/board/roster.yaml`
- `server/board/verification.py`
- `server/board/memory_review.py`
- `server/board/schemas.py`
- `server/members/*.md`
- `server/protocols/*.md`
- `hermes/skills/agentic-board/SKILL.md`
- `hermes/skills/board-memory-update/SKILL.md`
- `hermes/plugins/agentic_board/*`

External multi-agent systems remain useful inspiration, but they should not
override this product boundary: board members deliberate, Hermes operates, and
implementation agents build.
