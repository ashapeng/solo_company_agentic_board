# Runtime Flow

## Initiative-Native Founder Command Loop

```text
founder command
  -> initiative route suggestion
  -> founder override/approval
  -> board deliberation with initiative_id or ad hoc mode
  -> linked session JSON
  -> linked delegation tasks
  -> external action approvals
  -> closeout with founder outcome and carryover decisions
  -> board retrospective memory proposals
```

## Deliberation

```text
CLI or API request
  -> board deliberation
     -> classify query
     -> select active roster members
     -> run Stage 1 independent analysis
     -> run Stage 2 peer review
     -> run Stage 3 chair synthesis
     -> optionally verify and revise
  -> project stable decision fields
  -> propose SOTB memory update
  -> parse delegation plan
  -> save session JSON
  -> record harness ledger row
```

The board owns governance and judgment. It may produce memory and execution
proposals, but durable memory writes and delegated task execution live outside
the deliberation runtime.

## Learning Loop

```text
session JSON + harness ledger + founder feedback
  -> dry-run harness review or tuner
  -> proposed config changes
  -> human approval
  -> harness config update
  -> future board sessions use new routing, budgets, thresholds, or model choices
```

The first refactor preserves current behavior. Harness review still reruns
tuners on apply; exact approved-diff application is a follow-up hardening item.

## Execution Loop

```text
chair synthesis Delegation Plan
  -> execution task records
  -> human approval
  -> manager agent planning
  -> task status and artifact updates
```

Execution units are operating agents. They can be accountable to board members,
but they are not permanent board seats.
