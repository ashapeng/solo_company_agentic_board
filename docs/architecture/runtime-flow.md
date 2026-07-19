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

## Discovery Loop

```text
watchlist + source policy
  -> channel adapters fetch public records through safe HTTP rules
  -> raw records stored by ISO week
  -> deterministic corpus filtering/deduplication
  -> bounded agent bundle + analysis instructions
  -> IDE coding agent produces candidate topics (outside project LLM runtime)
  -> deterministic schema/evidence validation, enrichment, and ranking
  -> schema-v2 candidate persistence with separate lifecycle dimensions
  -> one bounded board portfolio review records a decision for every candidate
  -> up to three selected candidates (hard maximum five active)
  -> idempotent venture + activated validation initiative + experiment
  -> fake publisher only in Slice A; no external publication
```

Discovery failure is isolated from board deliberation. Import never starts the
board. Malformed portfolio output leaves candidate state unchanged and receives
one bounded repair attempt. No unavailable source is bypassed through an
authenticated browser.

### Founder-visible Slice A sequence

```text
optional migration dry-run/apply
  -> collect, prepare, synthesize, import
  -> inspect candidates
  -> review-portfolio
  -> receive stable decision/selection/experiment counts
  -> inspect candidate, portfolio-review, and experiment records locally
```

The implemented operator surface is the discovery CLI. There is no discovery
or experiment API/dashboard yet, and fake publishing is available only through
the injected test service. See
`opportunity-validation-user-experience.md` for the detailed journey graph.

## Memory Governance Loop

```text
board outcome or initiative closeout
  -> proposed SOTB entries/diff
  -> review against governed memory and venture scope
  -> explicit application
  -> snapshot + Markdown/index update
  -> optional consolidation and verification
  -> rollback remains available from snapshots
```

## API and UI Streaming

```text
React request
  -> POST /deliberate/stream
  -> API starts structured or live board task
  -> stage/member/clarification events enter an asyncio queue
  -> SSE frames stream to shared UI client
  -> UI reduces events into seat, stage, and decision state
  -> final session is persisted and returned as the terminal event
```

Disconnects cancel or finish according to the route's task lifecycle; provider
errors are converted into public error payloads rather than exposing secrets.
