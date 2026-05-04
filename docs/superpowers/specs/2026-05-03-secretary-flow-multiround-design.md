# Secretary Flow Refactor + Multi-Round CEO Loop

**Date:** 2026-05-03
**Status:** Implemented (Tasks 1-11 ✅, backend + frontend complete; Task 12 manual UI walkthrough pending user verification)
**Owner:** Peng

## Problem

The live-discussion flow in `server/board/deliberation/live.py` invokes the
Board Secretary **after every member's turn**, producing an interim "executive
brief" each time. With the default 5-turn loop, that means **6 secretary LLM
calls per meeting** (5 interim + 1 final) processing a transcript that grows
each turn. The output of the Secretary is also instructed (via
`server/members/secretary.md`) to follow a 7-level pyramid (one-liner, key
findings, decision options, conflict register, risk snapshot, action items,
detail index), which is verbose and clutters the CEO's view.

Additionally, the meeting today is one-shot: a single `/deliberate/live`
call runs one round of discussion, fires `chair_decision_required`, and ends.
There is no API path for the CEO to send a follow-up, get the board to
re-engage, and iterate.

## Goal

Three changes, scoped together:

1. **Eliminate interim Secretary briefs.** The Secretary should run **once per
   round**, only after all selected members have spoken (when control returns
   to the CEO).
2. **Slim Secretary output to a 4-section bullet format**: Agreements,
   Conflicts, Open Questions, Decision Needed From CEO. Drop pyramid.
3. **Add multi-round CEO re-engagement.** After the Secretary brief, the CEO
   can send a follow-up that triggers another round of member discussion,
   followed by another Secretary brief. Hard cap on follow-ups; explicit
   adjourn endpoint.

## Non-goals

- Staged-mode (`/deliberate`) flow — already correct (Secretary runs once).
- Mid-meeting member-set editing — selection locks at meeting start.
- WebSockets / persistent server-side queues — keep HTTP+SSE.
- New auth / session ownership model.
- Auto-write to State of the Board on adjourn — existing path stays.

## Decisions Locked During Brainstorming

| Decision | Choice |
|----------|--------|
| Scope | Multi-turn CEO loop in addition to interim-brief removal |
| Member selection per meeting | Keep current UI (manual checkbox or auto-classifier) |
| Round mechanics | Continuous conversation; no rigid round boundary semantics surfaced to user |
| Secretary output format | 4 sections: Agreements / Conflicts / Open Questions / Decision Needed From CEO |
| Meeting end | Hard cap (existing env `AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS`, default 2 follow-ups → 3 rounds total) **plus** explicit "Adjourn" UI button |
| Architecture | Approach 1 — stateless HTTP per round; new `/continue` and `/adjourn` endpoints; reuse session on disk |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ CEO (UI)                                                    │
│  - Meeting starts: pick members (manual/auto), enter Q1.    │
│  - After Secretary brief: "Send follow-up" or "Adjourn".    │
└─────────────────────────────────────────────────────────────┘
            │ POST /deliberate/live                ▲
            │ (round 1)                            │ SSE stream
            ▼                                      │
┌─────────────────────────────────────────────────────────────┐
│ FastAPI route → LiveDiscussion.run()                        │
│  • turn loop: members speak (router decides order/exit)     │
│  • NO interim Secretary brief inside loop                   │
│  • on loop exit: ONE Secretary brief (4-section bullets)    │
│  • emit chair_decision_required, end SSE                    │
│  • persist session w/ secretary_briefs[round_idx]           │
└─────────────────────────────────────────────────────────────┘
            │ POST /deliberate/live/{sid}/continue ▲
            │ (round 2..N, new SSE per round)      │
            ▼                                      │
┌─────────────────────────────────────────────────────────────┐
│ FastAPI route → LiveDiscussion(existing_session=...).run()  │
│  • load session from disk                                   │
│  • bump continuation_count; reject if ≥ MAX_CONTINUATIONS   │
│  • append CEO message; reset used_member_ids                │
│  • turn loop again → Secretary brief (cumulative transcript)│
└─────────────────────────────────────────────────────────────┘
            │ POST /deliberate/live/{sid}/adjourn
            ▼
┌─────────────────────────────────────────────────────────────┐
│ Mark session.status = "adjourned"; persist                  │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow & Session State

### Added/changed fields on `BoardSession`

```python
class BoardSession:
    # existing fields …
    status: str  # "running" | "awaiting_chair_decision" | "adjourned"
    continuation_count: int = 0          # NEW: # of CEO follow-ups so far (0 on first round)
    secretary_briefs: list[MemberResponse] = []  # NEW: one entry per round
    secretary_brief: MemberResponse | None       # KEEP: alias to secretary_briefs[-1]
    conversation: {
        "messages": [...],               # appends across rounds; never reset
        "routing_trace": [...],          # appends across rounds
    }
```

### Per-round state transitions

| Step | `status` | `continuation_count` | `used_member_ids` |
|------|----------|----------------------|-------------------|
| Round 1 start (POST `/live`) | `running` | 0 | `{}` |
| Members speak | `running` | 0 | fills up |
| Loop exits → Secretary brief | `awaiting_chair_decision` | 0 | full |
| CEO POST `/continue` accepted | `running` | 1 | **reset to `{}`** |
| Members speak again | `running` | 1 | fills again |
| Loop exits → Secretary brief | `awaiting_chair_decision` | 1 | full |
| CEO POST `/continue` (2nd) | `running` | 2 | reset |
| Loop exits → Secretary brief | `awaiting_chair_decision` | 2 | full |
| CEO POST `/continue` (3rd) | rejected (429); emit `meeting_capped` | unchanged | — |
| CEO POST `/adjourn` | `adjourned` | — | — |

`AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS=2` ⇒ max 3 rounds total.

### Transcript handling

Every round, the Secretary receives the **full conversation transcript** (all
messages, all rounds). Each Secretary brief is a rolling cumulative summary;
prior briefs remain in `secretary_briefs[]` for audit/replay, but the UI
foregrounds the latest.

Members in round 2+ see the cumulative `messages` list (their prior turns,
peers' turns, CEO follow-up, plus the previous Secretary brief). They evolve
their position rather than restart. `_format_full_transcript` already handles
this — no changes needed.

`used_member_ids` resets per round so members re-engage on each new CEO input.

## API Surface

### `POST /deliberate/live` (modified)

```
Body:  { query: str, members?: string[], options?: {...} }
Resp:  SSE stream
       events: turn_routed, message_delta, message_done,
               secretary_starting, secretary_delta, secretary_done,  ← only ONE per stream
               chair_decision_required, conversation_done
       Final state: session.status = "awaiting_chair_decision"
```

Removed: `secretary_*` events with `is_final=false` (interim briefs gone).

### `POST /deliberate/live/{session_id}/continue` (new)

```
Body:  { user_input: str }
Resp:  SSE stream (same event vocabulary as initial /live)
Errors:
  400 — empty user_input
  404 — session_id not found
  409 — session.status != "awaiting_chair_decision"
  429 — continuation_count >= MAX_CONTINUATIONS
        (server emits one final SSE event `meeting_capped`, then closes)
Side effects:
  - session.continuation_count += 1
  - session.conversation.messages append user message
  - used_member_ids reset to {}
  - LiveDiscussion(existing_session=...).run() executes one more turn loop
  - on loop exit: one Secretary brief appended to secretary_briefs[]
```

### `POST /deliberate/live/{session_id}/adjourn` (new)

```
Body:  { ceo_decision?: str }   # optional final CEO note for SOTB
Resp:  200 JSON { session_id, status: "adjourned", final_brief: {...} }
Errors:
  404 — session_id not found
  409 — session.status != "awaiting_chair_decision"
        (i.e., must let current round finish first)
Side effects:
  - session.status = "adjourned"
  - if ceo_decision provided: append as final user message to conversation
  - persist session
  - SOTB update path unchanged
```

`/adjourn` is idempotent: subsequent calls on already-adjourned session
return 200.

### Cap behaviour

Server checks `continuation_count >= MAX_CONTINUATIONS` before running the
turn loop. On reject: emit `{event: "meeting_capped", session_id,
max_continuations}` SSE event and close the stream with HTTP 429.

UI shows "Meeting cap reached. Adjourn to finalize." Only "Adjourn" remains
clickable; "Send follow-up" is disabled.

## Secretary Output Format

```markdown
## Agreements
- [bullet] — supported by [Strategist], [Architect], [Critic]
- [bullet] — supported by [Researcher], [Product]
(omit section if zero agreements)

## Conflicts
- **HARD** [topic]: [Member A] says X | [Member B] says NOT X
- **SOFT** [topic]: [Member A] prioritizes X | [Member B] prioritizes Y
(omit section if zero conflicts)

## Open Questions
- [unresolved question raised by Member(s)]
(omit section if zero open questions)

## Decision Needed From CEO
- [item requiring CEO ruling — phrased as question or choice]
(omit section if zero decisions needed)
```

### Hard limits (instructed via prompt)

- ≤ 5 bullets per section.
- Each bullet ≤ 25 words.
- Total brief ≤ 80 lines (incl. headers + blank lines).
- No prose paragraphs. No preamble. No closing remarks.
- Attribution required for every bullet (`[Member Title]`).
- Drop a section entirely if empty — never write `(none)` placeholder.

`max_tokens` for Secretary brief lowered from 3200 (`live.py:779`) to **1500**.

### Member-md changes (`server/members/secretary.md`)

- Replace **Procedure 3 (Hierarchical Summarization / Brief Pyramid)** with
  **Procedure 3 (Four-Section Bullet Brief)**.
- Collapse **Procedure 1 (Claim Extraction & Attribution)** into Procedure 3
  attribution requirement.
- Keep Procedures 2 (Conflict Detection), 4 (Precision Compression), 5
  (Neutrality Enforcement).
- Update **Anti-Patterns** to forbid: prose paragraphs, decision-options
  sections, risk snapshots, action items, detail indexes.
- Drop `[SOURCE]` inline tags and `[UNVERIFIED]` markers from Evidence
  Standards. Keep only `[Member Title]` attribution.

## Code Changes Per File

### `server/board/deliberation/live.py`

- DELETE lines 428-441 (per-turn `_produce_live_secretary_brief(is_final=False)` call).
- `LiveDiscussion.__init__`: accept optional `existing_session: BoardSession | None = None`. When provided, hydrate `session`, `messages`, `used_member_ids` from it. Bump `session.continuation_count`.
- `LiveDiscussion.run()`: at start, if `continuation_count >= max_continuations`, emit `meeting_capped` and return early.
- After turn loop, always call Secretary brief (current line 459-469 logic, unchanged) — the only call site now.
- `_produce_live_secretary_brief`: rename `is_final` → `round_index: int`. Drop `brief_mode` arg. Always persist (`session.secretary_briefs.append(...)`). Drop the `Persist only the final brief` conditional (line 856-857).
- Add `meeting_capped` SSE event helper.

### `server/board/deliberation/prompts.py`

- `format_live_secretary_brief`: new signature `(*, user_query, transcript, round_index)`. Body: 4-section template with inline rules. Drop interim/final branching (lines 564-580).
- `_FALLBACK_LIVE_SECRETARY` rewritten to new template.

### `server/members/secretary.md`

See "Member-md changes" above.

### `server/board/projection.py`

- Add `continuation_count: int = 0` to session shape.
- Add `secretary_briefs: list[dict] = []` to session shape.
- `secretary_brief` field projects `secretary_briefs[-1]` for back-compat with downstream readers expecting a single value.
- Add `"adjourned"` to allowed `status` values. (Cap state is encoded by `continuation_count` alone — no separate `"capped"` status.)

### `server/api/`

Locate live endpoint module. Add:

- `POST /deliberate/live/{session_id}/continue` route handler. Body: `{user_input: str}`. Returns SSE stream from `LiveDiscussion(existing_session=...).run()`. Error codes per API section above.
- `POST /deliberate/live/{session_id}/adjourn` route handler. Body: `{ceo_decision?: str}`. Idempotent. Returns JSON.

Existing `/deliberate/live` route: no signature change; ensure session is initialized with `continuation_count=0` and `secretary_briefs=[]`.

### `ui/src/shared/types.ts`

- `SecretaryBriefEvent`: drop `is_final`, `brief_mode`. Add `round_index: number`.
- Drop `Secretary-Interim` role; rename `Secretary-Final` → `Secretary`.
- Add `MeetingCappedEvent` type.
- `BoardSession`: add `continuation_count`, `secretary_briefs[]`.

### `ui/src/App.tsx`

- DELETE the `Secretary-Interim` rendering paths in `secretary_starting`/`_delta`/`_done` handlers (lines 423-494). Keep only the final-brief render (now just "Secretary").
- On `chair_decision_required`: render a follow-up prompt component with textarea + "Send follow-up" + "Adjourn" buttons. "Send follow-up" is disabled when `continuation_count >= max_continuations`.
- "Send follow-up" calls `POST /deliberate/live/{sid}/continue` → opens new SSE → renders new turn loop.
- "Adjourn" calls `POST /deliberate/live/{sid}/adjourn` → marks UI as closed, hides input.
- Handle `meeting_capped` event: show toast, disable follow-up button.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Session file corrupt on `/continue` load | 500 + log; UI shows "Session unavailable" |
| Secretary LLM call fails | Existing handler in `live.py:826-835` emits `secretary_failed`; persist empty `MemberResponse` with error in `secretary_briefs[]`; UI offers "brief failed; you can still send follow-up" |
| Member LLM call fails mid-loop | Existing behaviour unchanged (router skips, loop continues) |
| `/continue` while turn loop still running | 409 (status check requires `awaiting_chair_decision`) |
| Empty `user_input` on `/continue` | 400 + UI inline error |
| Concurrent `/continue` POSTs | First wins (status flips to `running`); second gets 409 |
| Process restart mid-meeting | Session on disk; CEO resumes by sending `/continue` |
| `/adjourn` on a still-running session | 409 |

## Edge Cases

1. **All sections empty** — Secretary brief is just headers. Acceptable; signals "nothing concrete yet."
2. **Single-member meeting** — Loop exits after one turn. Likely no Conflicts. Format omits empty sections gracefully.
3. **CEO repeats Q1 verbatim** — Members handle redundancy via existing "build on prior turns" instruction. Not our concern to detect.
4. **Member set picked at start, but CEO follow-up needs different expertise** — Locked at start by design. CEO must adjourn and start a new meeting if expertise mismatch.
5. **Brief blows length limit despite prompt** — Rely on prompt + `max_tokens=1500`. Log a soft warning if length exceeded; do not truncate server-side.
6. **Round 2 transcript exceeds context window** — Compaction in `compaction.py` is per-stage (not live). For now, log a warning when transcript > ~50 000 chars; defer truncation strategy to a follow-up.

## Testing

### Unit

- `format_live_secretary_brief` produces the 4-section template with correct `round_index` injection.
- `LiveDiscussion(existing_session=...)` correctly hydrates state and bumps `continuation_count`.
- Cap check rejects round 4 when `MAX_CONTINUATIONS=2`.

### Integration (existing pattern in `tests/test_shortcut_routing.py`)

- Full `/deliberate/live` → assert exactly one `secretary_done` event per round.
- Chain `/live` → `/continue` → `/continue` → `/continue` (last rejected with 429).
- `/live` → `/adjourn` (early adjourn from `awaiting_chair_decision`).

### Stubbed LLM

Use existing test harness; assert prompts and event sequences only.

### Manual UI walkthrough

`./start.sh`, drive a 3-round meeting in browser, send 2 follow-ups, hit cap, hit adjourn. Confirm no `Secretary-Interim` role appears in the conversation log.

## Acceptance Criteria

1. No interim Secretary brief calls in live mode (single Secretary call per round).
2. Secretary output is 4-section bullet format only; no pyramid.
3. CEO can send up to N follow-ups; cap enforced server-side.
4. CEO can adjourn at any `awaiting_chair_decision` checkpoint.
5. Per-round Secretary brief persisted in `session.secretary_briefs[]`.
6. Frontend renders only "Secretary" briefs (no `Interim`); shows follow-up + adjourn UI on `chair_decision_required`.

## Verification (before claiming done)

- `uv run pytest tests/` passes.
- Run `./start.sh`, drive a 3-round meeting in the browser, take a screenshot showing exactly N+1 Secretary briefs (where N = follow-ups sent).
- Token meter (`/metrics/summary`) shows ≥ 40 % reduction vs. pre-fix on an equivalent 5-turn single-round meeting.
