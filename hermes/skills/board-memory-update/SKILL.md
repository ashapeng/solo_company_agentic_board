---
name: board-memory-update
description: Review Agentic Board SOTB proposals and produce an approval-ready diff.
version: 0.1.0
platforms: [linux]
metadata:
  hermes:
    tags: [company, board, memory, sotb]
    category: business-ops
    requires_toolsets: [terminal, files]
---

# Board Memory Update Skill

Use this skill when a board session contains `memory.proposed_sotb_update`.

## When To Use

- The board produced a proposed SOTB update.
- The user asks whether to save a board learning.
- A prior board decision needs to be reviewed before becoming durable memory.

## When Not To Use

- Raw deliberation transcripts.
- Temporary implementation details.
- Unapproved strategy changes.
- Facts that belong in source-controlled docs rather than board memory.

## Procedure

1. Read the session JSON from `data/sessions/<session_id>.json`.
2. Extract `memory.proposed_sotb_update`.
3. If no proposal exists, stop. Do not invent memory.
4. Generate a review diff through the local API:

   ```bash
   curl -sS -X POST http://127.0.0.1:8000/sotb/review \
     -H 'Content-Type: application/json' \
     -d '{"session_id":"<session_id>","proposed_sotb_update":"<proposal>"}'
   ```

5. Present the diff and warnings to the user.
6. Ask for explicit approval before writing durable memory.
7. Apply only the approved text. Never auto-apply `memory.proposed_sotb_update`.

## Review Criteria

- The update records a durable decision, risk, established position, or open question.
- The update is short enough to keep SOTB compact.
- The update links back to the session id.
- The update does not overwrite unrelated SOTB sections.
- The update does not treat unverified claims as settled truth.

## Output

Return:

- approve / reject / edit recommendation
- diff summary
- warnings
- exact proposed text to apply, if approved
