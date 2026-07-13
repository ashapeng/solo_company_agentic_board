# Architecture Maintenance

Architecture documentation is part of the change, not a follow-up task.

## What counts as a significant architecture change

Update this folder in the same pull request when a change does any of the
following:

- adds/removes/renames a backend domain, API route module, frontend domain,
  external integration, persistent store, worker, or executable entry point;
- changes dependency direction or introduces a new cross-domain connection;
- changes a principal runtime flow, approval/trust boundary, authentication,
  remote-access behavior, or side-effect policy;
- changes an API/SSE event, session/task/memory schema, durable identifier, or
  file/database ownership used by more than one component;
- adds a major feature spanning two or more components.

Small internal refactors that preserve component responsibilities, connections,
interfaces, and data ownership do not require a diagram edit.

## Required update workflow

1. Update `component-catalog.json` if component inventory or paths changed.
2. Update `components.md` for ownership, interfaces, storage, or dependency
   changes.
3. Update `system-graph.md` for nodes, edges, boundaries, or principal flows.
4. Update `runtime-flow.md` when sequencing, gates, or failure behavior changed.
5. Record important trade-offs as a dated ADR in `docs/architecture/decisions/`
   using `000-template.md`.
6. Run `python3 scripts/check_architecture.py` and the relevant tests.

## Enforcement and limitations

The checker discovers architectural inventory changes from directory structure.
It fails for undocumented backend domains, API route modules, frontend domains,
missing catalog paths, duplicate IDs, or catalog entries absent from the main
component documentation and graph.

No static checker can infer every meaningful changed connection. Reviewers must
apply the significant-change rules above. The combination of structural drift
detection, a pull-request checklist, and ADRs keeps the model useful without
pretending the graph can be perfectly generated from imports.

## Review checklist

- [ ] Component responsibilities remain single and explicit.
- [ ] New arrows in the graph correspond to intentional dependencies.
- [ ] Domain code still does not depend on `server.api`.
- [ ] Side effects have an explicit approval/trust boundary.
- [ ] Data owner, lifecycle, and compatibility impact are documented.
- [ ] Tests cover new or changed cross-component contracts.
- [ ] `python3 scripts/check_architecture.py` passes.
