# Living Architecture

This folder is the architecture source of truth for Agentic Board. It describes
the system that exists in the repository, not a target-state design.

## Reading order

1. [system-graph.md](system-graph.md) — system context, component graph, and
   principal runtime flows (Mermaid diagrams render in GitHub and most IDEs).
2. [components.md](components.md) — responsibility, interfaces, dependencies,
   storage, and operational notes for every major component.
3. [runtime-flow.md](runtime-flow.md) — deliberation, execution, discovery,
   initiative, memory, and learning sequences.
4. [opportunity-validation-user-experience.md](opportunity-validation-user-experience.md)
   — detailed Slice A founder journey, guardrails, recovery paths, and state graph.
   Open [opportunity-validation-user-experience.html](opportunity-validation-user-experience.html)
   for the standalone interactive explorer.
5. [extension-guide.md](extension-guide.md) — how to add common capabilities.
6. [maintenance.md](maintenance.md) — the definition of an architecture-changing
   update and the required review/check workflow.
7. [discovery-to-board-evaluation.md](discovery-to-board-evaluation.md) — current
   discovery-to-portfolio-review and bounded-validation architecture.

`component-catalog.json` is the machine-readable inventory used by
`scripts/check_architecture.py`. It deliberately tracks architectural domains,
not every source file. The test suite runs the checker, so a newly introduced
backend domain, API route module, or frontend domain cannot silently bypass the
architecture review.

## Architectural style

The application is a local-first modular monolith:

- FastAPI and the CLI are inbound adapters.
- `server/board` is the governance core and coordinates deliberation.
- memory, execution, initiatives, ventures, discovery, experiments, and the harness are
  separate domain/data capabilities in the same process.
- React is a browser client of the HTTP/SSE API.
- JSON, JSONL, Markdown, YAML, and SQLite files under `data/` or domain-owned
  paths provide local persistence.
- model providers, source websites, search providers, and optional MCP servers
  are external dependencies behind adapters.

Domain packages must not import `server.api`; the API depends inward on domains.
Some domain-to-domain coordination remains direct Python imports, so this is a
modular monolith rather than strict hexagonal architecture.
