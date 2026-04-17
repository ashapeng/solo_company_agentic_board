# Agentic Board Plugin Scaffold

This is a local-only scaffold for the future Hermes plugin phase.

It is not registered with Hermes yet. The integration guide requires the local skill to be used
successfully for real decisions before promoting this to a first-class plugin.

The scaffold exposes the intended typed tools:

- `agentic_board_deliberate`
- `agentic_board_list_members`
- `agentic_board_read_sotb`
- `agentic_board_propose_sotb_update`
- `agentic_board_list_execution_agents`
- `agentic_board_get_delegation_plan`
- `agentic_board_approve_task`
- `agentic_board_plan_task`
- `agentic_board_update_task_status`
- `agentic_board_attach_task_artifact`

Memory writes are not exposed. `agentic_board_propose_sotb_update` calls `/sotb/review`, which
returns a diff and still requires human approval before any durable SOTB write.

Delegated task execution is approval-gated. Hermes should not run proposed or rejected tasks.
