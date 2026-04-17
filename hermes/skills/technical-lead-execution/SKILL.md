---
name: technical-lead-execution
description: Run an approved engineering delegated task through the Technical Lead Agent.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [engineering, execution, manager-agent]
    category: business-ops
    requires_toolsets: [terminal, files]
---

# Technical Lead Execution

Use this skill for approved tasks assigned to `technical_lead`.

## Procedure

1. Confirm the delegated task is approved.
2. Create or read its subtask plan.
3. Use scoped sub-agents for codebase exploration, implementation, and verification.
4. Keep all code changes test-backed and bounded to the task objective.
5. Mark the task completed only after verification artifacts are attached.
