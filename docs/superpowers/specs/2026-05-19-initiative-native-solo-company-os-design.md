# Initiative-Native Solo Company OS Design

Date: 2026-05-19

## Context

Agentic Board is currently a local-first board deliberation system with routed
board members, a State of the Board memory file, approval-gated delegated tasks,
execution-agent scaffolding, harness ledgers, and a web UI. It is directionally
aligned with a single-person company operating system, but the current runtime is
still centered on board sessions and delegated tasks rather than durable company
initiatives.

The target product is a solo-company operating OS. A gstack-style engineering
team is one execution department inside that larger system, not the whole
product. The first user is internal/private use, with packaging deferred until
the operating workflow is proven.

## Product Direction

The primary loop is the founder command loop:

1. The founder enters a business command in the web UI.
2. The system suggests whether to attach the command to an existing initiative,
   create a new draft initiative, or answer ad hoc.
3. The founder can override the suggestion before the board runs.
4. The board deliberates with initiative context when an initiative is selected.
5. Board sessions, delegated tasks, artifacts, and memory proposals attach to
   the initiative.
6. The founder approves the initiative before internal work proceeds.
7. Internal planning, research, and task preparation can proceed inside an
   approved initiative.
8. External actions remain separately approval-gated.
9. The founder closes the initiative with outcome, notes, and carryover
   decisions.
10. The board retrospective proposes memory updates.

The first durable operating unit is an initiative. An initiative represents a
time-boxed operating cycle, with a flexible timebox and a one-week default in
the UI.

## Goals

- Make initiatives a first-class runtime object, not a wrapper around sessions.
- Support manual initiative creation and auto-drafted initiatives from founder
  commands.
- Preserve ad hoc board sessions for one-off questions.
- Thread `initiative_id` through board sessions, delegated tasks, artifacts, and
  memory proposal references.
- Add a minimal web-first cockpit for founder commands, current initiative
  state, linked sessions, task groups, artifacts, approvals, memory context, and
  closeout.
- Add marketing as an execution unit accountable to the strategist.
- Keep the first slice narrow enough to implement and test safely.

## Non-Goals

- No department reports in the first closeout flow.
- No autonomous execution graduation in the first slice.
- No first-class finance or legal department in the first slice.
- No remote or multi-user SaaS authentication.
- No advanced metric-based initiative scoring.
- No Hermes plugin promotion.
- No full refactor of execution agents beyond what initiative ownership
  requires.

## Architecture

Add a new `server/initiatives/` domain.

Responsibilities:

- Initiative models and validation.
- Local persistence.
- Lifecycle transitions.
- Memory links.
- Artifact links.
- Session and task links.
- Closeout records.
- Carryover decisions.

Add `server/api/routes/initiatives.py`.

Core endpoints:

```text
GET    /initiatives
POST   /initiatives
GET    /initiatives/{id}
PATCH  /initiatives/{id}
POST   /initiatives/{id}/activate
POST   /initiatives/{id}/closeout
GET    /initiatives/{id}/sessions
GET    /initiatives/{id}/tasks
POST   /initiatives/{id}/links
DELETE /initiatives/{id}/links/{link_id}
```

Board integration:

- Extend board request schemas with `initiative_id` and `initiative_mode`.
- Supported initiative modes are `ad_hoc`, `attach`, and `create_draft`.
- Initiative-native board runs persist the initiative ID on the session record.
- The session adapter exposes initiative linkage.
- The board can still answer ad hoc without an initiative.

Execution integration:

- Add `initiative_id` to delegated tasks.
- Initiative-native task creation requires `initiative_id`.
- Legacy task parsing can keep `initiative_id` optional for migration and
  compatibility.
- Task listing supports filtering by initiative.
- External action gates are represented on tasks.

UI integration:

- Add `ui/src/domains/initiatives/` for types, API calls, and cockpit
  components.
- Keep the web UI as the canonical v1 interface.
- Keep CLI/API available for automation and tests.

Persistence:

- Use the existing local-first style.
- Store initiative tables in the same local SQLite ledger database initially,
  unless implementation discovers a strong reason to isolate them.

## Domain Model

```text
Initiative
- id
- title
- objective
- status: draft | active | closed
- timebox_start
- timebox_end
- success_criteria: list[str]
- departments: list[str]
- approval_state: draft | approved
- created_from: manual | founder_command | board_suggestion
- source_session_id: optional
- created_at
- updated_at
```

```text
InitiativeLink
- id
- initiative_id
- target_type: sotb_entry | initiative | board_session | delegated_task | artifact
- target_id
- relationship: context | output | carryover | evidence | artifact
- created_at
```

```text
InitiativeCloseout
- initiative_id
- founder_outcome: success | failure | mixed
- founder_notes
- retrospective_session_id
- memory_proposals: list/reference
- carryover_decisions:
  - task_id
  - decision: carry_over | abandon | backlog
  - target_initiative_id optional
- closed_at
```

Delegated task additions:

```text
initiative_id: optional for legacy, required for initiative-native routes
external_action_required: bool
external_action_type: outreach | publish | deploy | spend | none
```

## Initiative Routing

Before a board run, the system suggests one of three routes:

- Attach to an existing initiative.
- Create a new draft initiative.
- Run ad hoc.

The founder can override the suggestion before the board run starts. In v1 this
can be implemented with a simple hybrid approach: deterministic app rules plus
founder override. Deeper classifier or chair intake routing can be added later
after the model is stable.

One-off questions remain valid. Initiative-native means initiatives are the
first-class operating cycle when work is being organized, not that every board
question must become a permanent initiative.

## Approvals And Autonomy

V1 uses initiative-level approval:

- The founder approves the initiative before internal work proceeds.
- Internal planning, research, and coordination tasks can proceed inside an
  approved initiative.
- External actions require separate approval even inside an approved initiative.

External actions are:

- Sending outreach, email, or social posts.
- Publishing or deploying user-facing work.
- Spending money or committing to paid tools or services.

This leaves room for later autonomy graduation based on successful run history,
founder overrides, task outcomes, and recorded risks.

## Marketing Execution Unit

Marketing is an execution unit, not a board seat in v1.

Accountable board member: `strategist`.

Initial capabilities:

- Campaign planning.
- Outreach draft creation.
- Content and asset planning.
- Distribution experiments.
- Result analysis.

Marketing tasks that publish, send messages, or spend money are external
actions and require separate approval.

## Cockpit UI

The v1 cockpit should prioritize one screen:

- Founder command box.
- Initiative routing suggestion and override.
- Active initiative panel with title, objective, timebox, status, and success
  criteria.
- Department task groups for strategy, product, research, engineering,
  marketing, security, and operations.
- Approval queue for external actions.
- Linked sessions and artifacts.
- Memory context links suggested by the system and lightly editable by the
  founder.
- Closeout action for outcome, notes, carryover decisions, and retrospective.

Memory links should not become a manual burden. The system should suggest them
from SOTB entries, previous initiatives, board sessions, delegated tasks, and
artifacts. The founder can remove bad links or add missing links.

## Closeout

Initiative status values stay simple:

```text
draft | active | closed
```

Closeout records:

- Founder outcome: success, failure, or mixed.
- Founder notes.
- Board retrospective session reference.
- Memory proposals.
- Carryover decisions for unfinished tasks.

For unfinished tasks, the founder chooses:

- Carry over to a new or existing initiative.
- Abandon.
- Keep as backlog.

Department reports are deferred until execution managers perform more real work.

## First Implementation Slice

Build a narrow initiative-native vertical slice:

1. Add initiative persistence and API routes.
2. Add initiative request/response schemas.
3. Thread `initiative_id` through board requests, session records, session
   projection, and delegated tasks.
4. Add manual initiative creation and auto-draft from command.
5. Add activate and closeout flows.
6. Add carryover decision persistence.
7. Add marketing execution unit accountable to strategist.
8. Add minimal cockpit UI for initiative selection, active initiative, linked
   sessions, tasks, external-action approvals, artifacts, and closeout.
9. Preserve ad hoc board behavior.

## Testing Plan

Add or update tests for:

- Initiative CRUD.
- Initiative lifecycle: draft, active, closed.
- Board runs persist `initiative_id` on sessions.
- Delegation plans create initiative-linked tasks.
- Ad hoc board sessions still work.
- Initiative task listing returns linked tasks.
- Closeout records founder outcome and carryover decisions.
- External-action gates are represented on delegated tasks.
- Marketing execution unit is listed and accountable to strategist.
- UI smoke coverage for creating, activating, viewing, and closing an
  initiative.

Before or during implementation, address the current failing test baseline. The
latest local run produced 876 passing tests and 23 failures. The failures cluster
around delegated-task hook rate limits, Kimi base URL expectations, replay
patching, and SOTB governance async/event-loop behavior. Initiative-native core
changes should not be merged against an unexplained failing baseline.

## Open Decisions Resolved By This Spec

- Primary target: solo-company OS for internal use first.
- Engineering is one execution department inside the broader system.
- Main loop: founder command loop.
- Autonomy model: initiative approval first, external-action approval always.
- First-class v1 departments: current active set plus marketing execution.
- Initiative representation: time-boxed operating cycle.
- Interface: web UI first, CLI/API retained.
- Status lifecycle: draft, active, closed.
- Closeout: founder outcome, board retrospective, memory proposals, carryover
  decisions.
- First build scope: full thin vertical slice.
