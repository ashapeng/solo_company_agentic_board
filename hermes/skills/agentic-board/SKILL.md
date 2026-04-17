---
name: agentic-board
description: Invoke the local Agentic Board council service for high-leverage company decisions.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [company, board, strategy, decisions]
    category: business-ops
    requires_toolsets: [terminal, files]
---

# Agentic Board Skill

Use this skill when a decision needs C-suite governance, dissent, explicit tradeoff resolution,
or a durable company memory proposal.

## When To Use

- Strategic, product-defining, risky, or cross-functional decisions.
- Decisions where dissent matters more than a fast direct answer.
- Decisions that may update State of the Board memory.
- Major technical choices with product, customer, security, operational, or market consequences.
- Role evolution questions, such as whether to activate Guardian, Operator, Finance, or Legal.

## When Not To Use

- Simple factual lookups.
- Small implementation tasks.
- Formatting, summarization, or writing tasks.
- Procedural work already covered by an operating skill.
- Autonomous execution after a decision; execute only after the user approves the direction.

## Procedure

1. Restate the decision in one sentence. If the request is ambiguous, ask for the missing decision context.
2. Choose the board scope:
   - Default: let Agentic Board classify and route members.
   - Use `--full-board` only for broad company-level decisions.
   - Use `--members` only when the user explicitly asks for a specific council subset.
3. Prefer `--verify` for high-impact decisions.
4. Run from the repo root:

   ```bash
   .venv/bin/python -m server.cli --verify --budget "<question>"
   ```

   If `.venv/bin/python` is unavailable, use the Python interpreter documented by the local project.
5. Read the saved session JSON from the path printed by the CLI:

   ```text
   data/sessions/<session_id>.json
   ```

6. Present the board result using structured fields from the session JSON:
   - `decision.executive_summary`
   - `decision.strategic_direction`
   - `decision.next_steps`
   - `delegation_plan.tasks`
   - `decision.risk_register`
   - `decision.dissenting_views`
   - `verification`
   - `classification`
   - `memory.proposed_sotb_update`
7. Treat `memory.proposed_sotb_update` as a proposal only. Ask the user before applying durable memory.
8. Do not call `PUT /sotb`, `apply_sotb_update`, or write `server/memory/sotb.md` unless the user explicitly approves the exact update.
9. If the board output identifies `classification.unavailable_capabilities` or `classification.role_gap_memo`, surface it as a role-gap signal rather than silently ignoring it.
10. Convert approved `delegation_plan.tasks` into manager-agent operating workflows only after the user approves execution.

## Stage Profiles

The board stage profile controls which C-suite seats are active:

- `pre_pmf`: default. Active members are CEO, CSO, CPO, acting CCO, CTO, risk director, and execution feasibility.
- `live_product`: activates CISO/Guardian and COO/Operator.
- `revenue`: reserves space for CFO/Finance and Legal when those members exist.

Set the profile before invoking the board if the user or situation requires it:

```bash
BOARD_STAGE_PROFILE=live_product .venv/bin/python -m server.cli --verify --budget "<question>"
```

## Output Contract

The session JSON is the integration contract. Do not parse CLI rich text as the source of truth.

Expected stable fields:

```json
{
  "session_id": "board_...",
  "classification": {
    "query_type": "security",
    "relevant_member_ids": ["chairperson", "critic", "architect"],
    "required_capabilities": ["threat_modeling", "data_privacy"],
    "unavailable_capabilities": ["threat_modeling"],
    "stage_profile": "pre_pmf",
    "role_gap_memo": "..."
  },
  "decision": {
    "executive_summary": "...",
    "strategic_direction": "...",
    "next_steps": ["..."],
    "risk_register": ["..."],
    "dissenting_views": ["..."]
  },
  "delegation_plan": {
    "tasks": [
      {
        "id": "board_..._task_1",
        "manager_agent_id": "technical_lead",
        "execution_unit_id": "engineering",
        "status": "proposed",
        "approval_required": true
      }
    ]
  },
  "verification": {
    "score": 8,
    "passed": true,
    "deficiencies": [],
    "suggestions": []
  },
  "memory": {
    "proposed_sotb_update": "...",
    "requires_approval": true
  }
}
```

## Failure Modes

- If the CLI fails because provider credentials are missing, tell the user the board could not run and cite the local environment issue.
- If classification falls back to `full-board`, proceed but mention the fallback.
- If `memory.proposed_sotb_update` is missing, do not invent memory.
- If `verification.passed` is false, present the deficiency and do not treat the decision as final without user review.
- If the required capability is unavailable in the active stage profile, recommend a role-gap review only if this is likely to recur.
