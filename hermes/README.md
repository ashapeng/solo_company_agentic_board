# Hermes Integration

This directory contains source-controlled Hermes artifacts for Agentic Board.

Hermes is intentionally not a dependency of this Python project. Install and configure Hermes
at the user/runtime level, then either:

- point Hermes at this repo's `hermes/skills/` directory as an external skills directory, or
- sync `hermes/skills/agentic-board/SKILL.md` to `~/.hermes/skills/agentic-board/SKILL.md`.

The first integration path uses the local CLI and reads the saved session JSON. Do not expose
the API remotely unless auth is added.

Current artifacts:

- `skills/agentic-board/SKILL.md`: call the board and read session JSON.
- `skills/board-memory-update/SKILL.md`: review proposed SOTB updates before approval.
- `skills/role-gap-review/SKILL.md`: decide whether blind spots need a skill or board role.
- `skills/board-decision-to-sprint/SKILL.md`: route approved delegated tasks to manager agents.
- `skills/*-lead-execution/SKILL.md`: manager-agent execution playbooks.
- `plugins/agentic_board/`: local-only plugin scaffold for a later Hermes registration step.
