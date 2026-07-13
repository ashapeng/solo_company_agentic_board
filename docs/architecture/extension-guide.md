# Extension Guide

## Add A Board Member

1. Add or update a member markdown file in `server/members/`.
2. Add roster metadata in `server/board/roster/roster.yaml`.
3. Add or update a benchmark query in the role-gap review material.
4. Run roster, routing, full-council, and protocol tests.

Use `server.board.role_gap.review_role_gap()` before adding durable members.
One-off operating work should become a Hermes skill or execution workflow first.

## Add An Execution Unit

1. Add the manager agent and templates in `server/execution/agents.py`.
2. Confirm the derived unit appears through `server/execution/units.py`.
3. Map delegated task inference keywords in `server/execution/tasks.py` if needed.
4. Run execution and API tests.

Execution units are approval-gated operating capabilities, not board members.

## Add A Validation Action

1. Add the typed action beneath `server/experiments/`.
2. Keep inputs and outputs allowlisted and experiment-scoped.
3. Add idempotency, timeouts, redacted errors, and audit events.
4. Use a fake adapter in default tests; live actions must be opt-in.

Validation actions never enable `execution.always_on_enabled` globally.

## Add A Harness Tuner

1. Add the tuner module under `server/harness/`.
2. Read data from `server.harness.ledger`.
3. Write proposed or approved settings through `server.harness.config`.
4. Add it to `server/harness/reviews.py` if it should participate in review runs.
5. Add contract tests with dry-run and save behavior.

Tuners should preserve unrelated config metadata.

## Add An API Route

1. Add the route to the domain module in `server/api/routes/`.
2. Put shared request models in `server/api/schemas.py`.
3. Export direct-test compatibility names from `server/api/__init__.py` only when tests or callers need them.
4. Keep domain packages independent from `server.api`.

## Add UI Surface

1. Put shared wire types in `ui/src/shared/types.ts`.
2. Put fetch/SSE calls in `ui/src/shared/api.ts`.
3. Export domain entrypoints from `ui/src/domains/<domain>/index.ts`.
4. Move visual components into the matching domain folder when they are split out of `App.tsx`.
