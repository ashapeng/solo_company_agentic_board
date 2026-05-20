# Architecture Overview

Agentic Board is organized by domain so new contributors can find the right layer
without reading the full runtime.

## Backend Domains

| Domain | Path | Owns |
| --- | --- | --- |
| Board governance | `server/board/` | Members, roster, deliberation stages, chair synthesis, decision projection |
| Harness learning | `server/harness/` | Tunable config, outcome ledger, token/routing/model/verification tuners, harness reviews |
| Execution units | `server/execution/` | Manager agents, execution units, delegated task state, evidence packets |
| Initiatives | `server/initiatives/` | Time-boxed operating cycles, links, closeouts, carryovers |
| Memory | `server/memory/` | SOTB read helpers, SOTB proposals, reviewable diffs, guarded memory writes |
| API | `server/api/` | FastAPI app assembly, request models, route modules by domain |
| Integrations | `hermes/` | Optional Hermes skills and plugin adapters |

Compatibility shims remain under `server/board/*.py` for the first migration
phase. New code should import the domain packages directly.

## Frontend Domains

| Domain | Path | Owns |
| --- | --- | --- |
| Board UI | `ui/src/domains/board/` | Board session types and board API entrypoints |
| Execution UI | `ui/src/domains/execution/` | Execution agent/task types and task actions |
| Harness UI | `ui/src/domains/harness/` | Metrics and harness review entrypoints |
| Initiatives UI | `ui/src/domains/initiatives/` | Initiative cockpit, initiative API types, closeout controls |
| Memory UI | `ui/src/domains/memory/` | SOTB and feedback entrypoints |
| Shared | `ui/src/shared/` | API client primitives and shared TypeScript types |

`ui/src/App.tsx` still owns the primary screen composition after this refactor.
Future UI cleanup should move large visual components into the domain folders.
