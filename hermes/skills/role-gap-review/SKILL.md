---
name: role-gap-review
description: Decide whether repeated board blind spots need a skill, shelved member, or new board member.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [company, board, roster, governance]
    category: business-ops
    requires_toolsets: [terminal, files]
---

# Role Gap Review Skill

Use this skill when Agentic Board reports `classification.unavailable_capabilities` or a
`classification.role_gap_memo`.

## When To Use

- A required capability is missing from the active stage profile.
- The same blind spot appears in two or more sessions.
- The user asks whether to activate Guardian, Operator, Finance, Legal, or another board role.

## When Not To Use

- A one-off task that can be handled procedurally.
- A narrow execution task better suited to an operating skill.
- A preference for more agents without evidence of better decisions.

## Procedure

1. Read the session JSON and capture:
   - `classification.unavailable_capabilities`
   - `classification.stage_profile`
   - `classification.role_gap_memo`
   - the original `user_query`
2. Estimate recurrence count from known sessions. If unknown, use `1`.
3. Ask the local board helper for a recommendation:

   ```bash
   curl -sS -X POST http://127.0.0.1:8000/role-gap/review \
     -H 'Content-Type: application/json' \
     -d '{"missing_capabilities":["threat_modeling"],"query":"<query>","stage_profile":"pre_pmf","recurrence_count":1}'
   ```

4. Recommend exactly one of:
   - `no_change`
   - `create_hermes_skill`
   - `activate_shelved_member`
   - `create_new_board_member`
5. Include a benchmark query that would prove the change improves board decisions.
6. Require human approval before changing member files, roster profiles, or durable memory.

## Decision Rules

- One-off gap: prefer `create_hermes_skill` or `no_change`.
- Repeated gap covered by `_guardian.md` or `_operator.md`: prefer `activate_shelved_member`.
- Repeated gap not covered by a shelved member: consider `create_new_board_member`.
- Never add a board member without a written rationale and benchmark query.
