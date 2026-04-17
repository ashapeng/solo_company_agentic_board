---
name: operations-lead-execution
description: Run an approved operations delegated task through the Operations Lead Agent.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [operations, release, execution, manager-agent]
    category: business-ops
    requires_toolsets: [terminal, files]
---

# Operations Lead Execution

Use this skill for approved tasks assigned to `operations_lead`.

## Procedure

1. Confirm the delegated task is approved.
2. Create or read its subtask plan.
3. Produce release, monitoring, incident, or runbook artifacts.
4. Attach operational artifacts and update task status.
