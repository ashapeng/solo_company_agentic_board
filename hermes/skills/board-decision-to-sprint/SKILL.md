---
name: board-decision-to-sprint
description: Convert an approved Agentic Board delegation plan into manager-agent execution work.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [company, board, delegation, execution]
    category: business-ops
    requires_toolsets: [terminal, files]
---

# Board Decision To Sprint

Use this skill after Agentic Board returns `delegation_plan.tasks`.

## Procedure

1. Read the session delegation plan through the local board API.
2. Ask for approval before executing any task with `status=proposed`.
3. Approve only the tasks the user explicitly accepts.
4. For each approved task, call the matching manager-agent execution skill.
5. Write progress back through `/delegated-tasks/{task_id}/status`.
6. Attach artifacts through `/delegated-tasks/{task_id}/artifacts`.

Never execute a proposed or rejected task.
