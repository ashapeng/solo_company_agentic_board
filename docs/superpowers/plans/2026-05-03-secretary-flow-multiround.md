# Secretary Single-Brief + Multi-Round CEO Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate per-turn Secretary briefs in live mode, slim the Secretary output to a four-section bullet format, and add continue/adjourn endpoints so the CEO can re-engage the board across multiple rounds in a single meeting.

**Architecture:** Stateless HTTP per round. The existing live route (`POST /deliberate/stream` with `discussion_mode: "live"`) starts a meeting and returns one Secretary brief at the end. Two new session-scoped endpoints — `POST /sessions/{session_id}/continue` (streams another round) and `POST /sessions/{session_id}/adjourn` (closes the meeting) — let the CEO continue the conversation. The cap is enforced server-side via `AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS` (default 2 follow-ups → 3 rounds total).

**Tech Stack:** FastAPI + SSE, Python 3.11 dataclasses, async LLM streaming, React + TypeScript frontend, pytest.

**Spec:** `docs/superpowers/specs/2026-05-03-secretary-flow-multiround-design.md`

## File Structure

| File | Responsibility |
|------|----------------|
| `server/members/secretary.md` | Member system prompt — replace pyramid procedure with four-section bullet procedure |
| `server/board/deliberation/prompts.py` | `format_live_secretary_brief` simplified; new fallback template |
| `server/board/deliberation/orchestrator.py` | `BoardSession` dataclass — add `continuation_count`, `secretary_briefs`, alias `secretary_brief` to last entry |
| `server/board/deliberation/live.py` | `LiveBoardConversation.discuss()` — drop interim-brief call site, add `existing_session` resume, cap check, persist briefs to list |
| `server/api/schemas.py` | `ContinueRequest`, `AdjournRequest` Pydantic models |
| `server/api/routes/board.py` | `POST /sessions/{sid}/continue` and `POST /sessions/{sid}/adjourn` route handlers |
| `tests/test_secretary_brief_prompt.py` | NEW — unit tests for the four-section template |
| `tests/test_live_secretary_single_brief.py` | NEW — unit tests for one-brief-per-round behaviour |
| `tests/test_continue_adjourn_endpoints.py` | NEW — endpoint contract tests |
| `ui/src/shared/types.ts` | Drop `Secretary-Interim`; add `MeetingCapped` event; extend `BoardSession` |
| `ui/src/App.tsx` | Drop interim render; add follow-up + adjourn UI on `chair_decision_required` |

---

## Task 1: Update Secretary system prompt to four-section bullet brief

**Files:**
- Modify: `server/members/secretary.md`

This task is content-only (a Markdown member definition). No automated test — Task 3 covers the prompt template that injects this content; Task 4 covers brief production end-to-end.

- [ ] **Step 1: Open `server/members/secretary.md` and replace Procedure 3 (lines 54-64) with the four-section procedure**

Replace the block:

```markdown
### Procedure 3: Hierarchical Summarization (The Brief Pyramid)
**Trigger:** Producing the final brief structure.
**Steps:**
1. **Level 1 — One-liner:** Single sentence: decision context + recommendation direction.
2. **Level 2 — Key Findings (3-7 bullets):** What the board agrees on, disagrees on, and what's uncertain. Each bullet attributes the source(s).
3. **Level 3 — Decision Options (if applicable):** Paths forward, with pros/cons per option, attributed.
4. **Level 4 — Conflict Register:** All flagged conflicts with both sides and resolution suggestions.
5. **Level 5 — Risk Snapshot:** Top risks with probability, impact, mitigations, and who raised each.
6. **Level 6 — Action Items:** Who does what, by when, with acceptance criteria.
7. **Level 7 — Detail Index:** Line-level index pointing back to specific members' original text for deep-dive.
**Output:** A pyramid-structured brief that rewards scanning and enables drilling.
```

with:

```markdown
### Procedure 3: Four-Section Bullet Brief
**Trigger:** Producing every Secretary brief (live or staged).
**Steps:**
1. Emit only these four headers, in this exact order, omitting any header whose body would be empty:
   `## Agreements`
   `## Conflicts`
   `## Open Questions`
   `## Decision Needed From CEO`
2. Each section contains bullets only. No prose paragraphs. No preamble. No closing remarks.
3. Cap each section at 5 bullets. Cap each bullet at 25 words.
4. Every bullet includes attribution in square brackets, e.g. `[Strategist]` or `[Strategist, Architect]`. Use member titles, not IDs.
5. Conflicts are formatted as `**HARD** [topic]: [Member A] says X | [Member B] says NOT X` for direct contradictions, or `**SOFT** [topic]: [Member A] prioritizes X | [Member B] prioritizes Y` for tensions.
6. Decision-Needed items are phrased as questions or A/B choices the CEO can rule on directly.
7. The whole brief MUST fit in 80 lines (including blank lines between sections). If unable to fit, drop the lowest-priority bullets in this order: Open Questions → Agreements → Conflicts → Decision Needed.
**Output:** A scannable four-section bullet brief, ≤ 80 lines.
```

- [ ] **Step 2: Update Procedure 1 (Claim Extraction & Attribution) attribution rule**

Replace lines 41-42 (the "Output" line of Procedure 1) so attribution requirements feed directly into Procedure 3:

```markdown
**Output:** A claim ledger keyed by `[Member Title]` ready for use as bullet attributions in Procedure 3. Do NOT emit the ledger separately — it is intermediate scratch data.
```

- [ ] **Step 3: Update Anti-Patterns section (lines 97-103)**

Replace the existing list with:

```markdown
- Do NOT introduce new claims, analysis, or recommendations not present in the deliberation.
- Do NOT silently resolve conflicts by presenting only one side.
- Do NOT use vague attribution ("the board thinks") — always name the specific member(s).
- Do NOT produce a wall of text — the brief MUST fit in 80 lines and be scannable in under 60 seconds.
- Do NOT flatten disagreements into a false consensus — CEOs need to see where the board is divided.
- Do NOT reorder or reframe members' words to change their apparent meaning.
- Do NOT emit any section beyond the four allowed: Agreements, Conflicts, Open Questions, Decision Needed From CEO.
- Do NOT emit decision-options pros/cons tables, risk snapshots with probability/impact, action items with owners/dates, or detail indexes — those formats are deprecated.
- Do NOT include `[SOURCE]` inline tags, `[UNATTRIBUTED]` markers, or `[UNVERIFIED]` markers. Use plain `[Member Title]` attribution only.
```

- [ ] **Step 4: Simplify the Evidence Standards section (lines 112-118)**

Replace with:

```markdown
- Every bullet in the brief MUST be traceable to a specific member's response.
- Use `[Member Title]` attribution. For multiple sources: `[Strategist, Researcher]`.
- If a claim cannot be attributed to any specific member, drop it — do not include unattributed material.
- When a member cited external evidence, you MAY parenthesise the source name after the attribution: `[Strategist (cites McKinsey 2024)]`.
```

- [ ] **Step 5: Verify the file still parses by listing members**

Run: `uv run python -m server.cli --list-members`
Expected: Table prints all members including `secretary` with no parsing errors.

- [ ] **Step 6: Commit**

```bash
git add server/members/secretary.md
git commit -m "feat(secretary): switch system prompt to four-section bullet brief

Replace the seven-level pyramid procedure with a four-section format
(Agreements / Conflicts / Open Questions / Decision Needed From CEO),
cap each section to 5 bullets and 25 words per bullet, and tighten the
anti-patterns and evidence standards to forbid the deprecated formats.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Add unit tests for the new Secretary prompt template (failing first)

**Files:**
- Create: `tests/test_secretary_brief_prompt.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_secretary_brief_prompt.py`:

```python
"""Contract tests for the live Secretary brief prompt template."""

import unittest

from server.board.deliberation.prompts import format_live_secretary_brief


class SecretaryBriefPromptTest(unittest.TestCase):
    def test_signature_accepts_round_index_and_no_brief_mode(self) -> None:
        # New signature: only user_query, transcript, round_index. No brief_mode/is_final.
        prompt = format_live_secretary_brief(
            user_query="Should we ship feature X?",
            transcript="[Strategist] Validate demand first.\n[Architect] Spike feasibility.",
            round_index=0,
        )
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)

    def test_prompt_lists_the_four_required_sections(self) -> None:
        prompt = format_live_secretary_brief(
            user_query="Q",
            transcript="t",
            round_index=0,
        )
        for header in ("## Agreements", "## Conflicts", "## Open Questions", "## Decision Needed From CEO"):
            self.assertIn(header, prompt, f"prompt must reference required section: {header}")

    def test_prompt_forbids_deprecated_sections(self) -> None:
        prompt = format_live_secretary_brief(
            user_query="Q",
            transcript="t",
            round_index=0,
        )
        for forbidden in ("Risk Snapshot", "Action Items", "Detail Index", "Decision Options", "One-liner"):
            self.assertNotIn(forbidden, prompt, f"deprecated section name leaked into prompt: {forbidden}")

    def test_prompt_announces_round_index_for_continuations(self) -> None:
        prompt_round_0 = format_live_secretary_brief(user_query="Q", transcript="t", round_index=0)
        prompt_round_2 = format_live_secretary_brief(user_query="Q", transcript="t", round_index=2)
        # Round 0 prompt should not mention "follow-up"; round 2 should.
        self.assertIn("Round 0", prompt_round_0)
        self.assertIn("Round 2", prompt_round_2)
        self.assertIn("follow-up", prompt_round_2.lower())

    def test_prompt_caps_brief_to_eighty_lines(self) -> None:
        prompt = format_live_secretary_brief(user_query="Q", transcript="t", round_index=0)
        # The instruction must explicitly mention the 80-line cap.
        self.assertIn("80 lines", prompt)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_secretary_brief_prompt.py -v`
Expected: ALL tests FAIL — current `format_live_secretary_brief` signature still has `brief_mode` and `is_final`; template still emits pyramid sections.

- [ ] **Step 3: Commit (failing test, locks the contract)**

```bash
git add tests/test_secretary_brief_prompt.py
git commit -m "test(prompts): contract for new four-section live Secretary brief

Asserts the new signature, presence of the four required headers,
absence of deprecated section names, round-index injection, and the
80-line cap instruction.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Implement the new four-section live Secretary prompt template

**Files:**
- Modify: `server/board/deliberation/prompts.py:560-590`

- [ ] **Step 1: Read the current `format_live_secretary_brief` and its fallback string**

Run: `grep -n "_FALLBACK_LIVE_SECRETARY\|format_live_secretary_brief\|live_secretary_brief" server/board/deliberation/prompts.py`
Note the line numbers of `_FALLBACK_LIVE_SECRETARY` definition and the function so the next step replaces them in place.

- [ ] **Step 2: Replace the `_FALLBACK_LIVE_SECRETARY` constant**

Locate the constant (it is a multi-line string above `format_live_secretary_brief`). Replace its full body with:

```python
_FALLBACK_LIVE_SECRETARY = """{{secretary_system_prompt}}

You are producing the Secretary brief for **Round {{round_index}}** of a live board meeting.{{round_hint}}

The CEO's question: {{user_query}}

Full transcript so far:
{{transcript}}

## Output rules

Emit only these four section headers, in this order, omitting any whose body would be empty:

1. `## Agreements` — bullets the board agrees on, each ending with `[Member Title]` attribution.
2. `## Conflicts` — `**HARD** [topic]: [Member A] says X | [Member B] says NOT X` for direct contradictions, or `**SOFT** [topic]: [Member A] prioritizes X | [Member B] prioritizes Y` for tensions.
3. `## Open Questions` — unresolved questions raised by one or more members, attributed.
4. `## Decision Needed From CEO` — items requiring a CEO ruling, phrased as questions or A/B choices.

Hard caps:
- Maximum 5 bullets per section.
- Maximum 25 words per bullet.
- The whole brief MUST fit in 80 lines (including blank lines between sections).
- No prose paragraphs. No preamble. No closing remarks.
- Drop a section entirely if empty — never write `(none)` placeholder.
- Forbidden: Risk Snapshot, Action Items, Detail Index, Decision Options, One-liner. Do not emit any of those formats.
"""
```

- [ ] **Step 3: Replace the `format_live_secretary_brief` function (lines 560-590)**

Replace the entire function body with:

```python
def format_live_secretary_brief(*, user_query: str, transcript: str, round_index: int) -> str:
    """Build a Secretary prompt for a live discussion transcript.

    Single-mode template — no interim/final dimension. Each call corresponds to
    one round (round_index 0 = initial CEO query, 1+ = CEO follow-ups).
    """
    template = _load_or_fallback("live_secretary_brief", _FALLBACK_LIVE_SECRETARY)

    if round_index == 0:
        round_hint = ""
    else:
        round_hint = (
            f" The CEO has sent {round_index} follow-up(s); incorporate the latest "
            "follow-up content alongside prior turns."
        )

    return (
        template
        .replace("{{secretary_system_prompt}}", "")
        .replace("{{user_query}}", user_query)
        .replace("{{transcript}}", transcript)
        .replace("{{round_index}}", str(round_index))
        .replace("{{round_hint}}", round_hint)
    )
```

- [ ] **Step 4: Search for any external Markdown protocol file referenced by `_load_or_fallback("live_secretary_brief", ...)`**

Run: `find server/protocols -name "live_secretary*" 2>/dev/null`

If a file `server/protocols/live_secretary_brief.md` exists, open it and update its content to mirror `_FALLBACK_LIVE_SECRETARY`. If it does not exist, the fallback is the source of truth — skip this step.

- [ ] **Step 5: Run the prompt unit tests to verify they pass**

Run: `uv run pytest tests/test_secretary_brief_prompt.py -v`
Expected: 5 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/board/deliberation/prompts.py server/protocols/live_secretary_brief.md 2>/dev/null; git add server/board/deliberation/prompts.py
git commit -m "feat(prompts): four-section live Secretary brief template

Drop is_final/brief_mode dimensions. Add round_index parameter to
distinguish initial round 0 from CEO follow-ups. Hardcode the four
required sections, attribution rules, hard caps, and the 80-line ceiling
into the fallback template body so the LLM cannot revert to pyramid
output.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Add `continuation_count` and `secretary_briefs[]` to `BoardSession`

**Files:**
- Modify: `server/board/deliberation/orchestrator.py:64-115`
- Test: `tests/test_secretary_brief_prompt.py` (extend) OR a new `tests/test_board_session_shape.py`

Use a new dedicated test file for clarity.

- [ ] **Step 1: Write the failing test**

Create `tests/test_board_session_shape.py`:

```python
"""Contract tests for BoardSession multi-round fields."""

import unittest

from server.board.deliberation.orchestrator import BoardSession, MemberResponse


class BoardSessionShapeTest(unittest.TestCase):
    def test_default_continuation_count_is_zero(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        self.assertEqual(session.continuation_count, 0)

    def test_default_secretary_briefs_is_empty_list(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        self.assertEqual(session.secretary_briefs, [])

    def test_secretary_brief_alias_returns_last_brief(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        first = MemberResponse(member_id="secretary", stage=4, content="round 0 brief", model="m", elapsed_seconds=0.1)
        second = MemberResponse(member_id="secretary", stage=4, content="round 1 brief", model="m", elapsed_seconds=0.1)
        session.secretary_briefs.append(first)
        self.assertIs(session.secretary_brief, first)
        session.secretary_briefs.append(second)
        self.assertIs(session.secretary_brief, second)

    def test_secretary_brief_alias_returns_none_when_empty(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        self.assertIsNone(session.secretary_brief)

    def test_to_dict_serializes_continuation_count_and_briefs(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        session.continuation_count = 2
        session.secretary_briefs.append(
            MemberResponse(member_id="secretary", stage=4, content="b", model="m", elapsed_seconds=0.1)
        )
        as_dict = session.to_dict()
        self.assertEqual(as_dict["continuation_count"], 2)
        self.assertEqual(len(as_dict["secretary_briefs"]), 1)
        self.assertEqual(as_dict["secretary_briefs"][0]["content"], "b")
        # Back-compat: secretary_brief still surfaces the latest entry.
        self.assertEqual(as_dict["secretary_brief"]["content"], "b")

    def test_status_can_be_adjourned(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        session.status = "adjourned"
        self.assertEqual(session.status, "adjourned")
        self.assertEqual(session.to_dict()["status"], "adjourned")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_board_session_shape.py -v`
Expected: All 6 tests FAIL — fields don't exist; alias property doesn't exist; to_dict doesn't serialize new fields.

- [ ] **Step 3: Read the current `BoardSession` dataclass at orchestrator.py:64-130 to plan the edit**

Run: `sed -n '60,135p' server/board/deliberation/orchestrator.py`
Note the exact line of `secretary_brief: MemberResponse | None = None` and the `to_dict()` body.

- [ ] **Step 4: Replace the existing `secretary_brief` declaration and the `to_dict()` method with the multi-brief version**

In `server/board/deliberation/orchestrator.py`:

Locate this line in the dataclass body:

```python
    secretary_brief: MemberResponse | None = None
```

Replace it with:

```python
    secretary_briefs: list[MemberResponse] = field(default_factory=list)
    continuation_count: int = 0

    @property
    def secretary_brief(self) -> MemberResponse | None:
        """Latest Secretary brief — alias for `secretary_briefs[-1]` for back-compat."""
        return self.secretary_briefs[-1] if self.secretary_briefs else None

    @secretary_brief.setter
    def secretary_brief(self, value: MemberResponse | None) -> None:
        """Setter retained for back-compat: appends to `secretary_briefs` if non-None.

        New code should use `secretary_briefs.append(...)` directly.
        """
        if value is not None:
            self.secretary_briefs.append(value)
```

Then locate the `to_dict()` method body (just below the dataclass fields). Find the line:

```python
            "secretary_brief": _resp(self.secretary_brief) if self.secretary_brief else None,
```

Replace it with:

```python
            "secretary_brief": _resp(self.secretary_brief) if self.secretary_brief else None,
            "secretary_briefs": [_resp(b) for b in self.secretary_briefs],
            "continuation_count": self.continuation_count,
```

(The first line stays — it now resolves through the property to the latest brief.)

- [ ] **Step 5: Run the shape test to verify it passes**

Run: `uv run pytest tests/test_board_session_shape.py -v`
Expected: 6 tests PASS.

- [ ] **Step 6: Update `adapt_session_record` to surface the new fields**

In `server/board/projection.py`, locate the dict returned by `adapt_session_record` (around lines 126-147). Add two keys in the returned dict, alongside `secretary_brief`:

```python
        "secretary_brief": secretary_brief_content,
        "secretary_briefs": record.get("secretary_briefs") or [],
        "continuation_count": record.get("continuation_count", 0),
```

This lets the UI restore cap state and full brief history when cold-loading a session via `/sessions/{sid}/adapter`. Existing readers that ignore unknown keys are unaffected.

- [ ] **Step 7: Run the full test suite to confirm no other test broke**

Run: `uv run pytest tests/ -x --timeout=60`
Expected: All previously-passing tests still pass. (Some live-discussion tests may need follow-up adjustment in later tasks; if they fail here it should ONLY be due to interim/final assertions which we will fix in Task 6.)

If a non-live test fails, stop and investigate before continuing.

- [ ] **Step 8: Commit**

```bash
git add server/board/deliberation/orchestrator.py server/board/projection.py tests/test_board_session_shape.py
git commit -m "feat(board): multi-round secretary briefs on BoardSession

Add secretary_briefs list and continuation_count fields. Keep
secretary_brief as a property alias to secretary_briefs[-1] so existing
readers (projection, frontend, tests) continue to work. to_dict()
serialises both the alias and the full list plus the continuation
count. adapt_session_record forwards the new fields so cold-loaded
sessions restore cap state and brief history.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Refactor `_produce_live_secretary_brief` to single-mode + per-round persistence

**Files:**
- Modify: `server/board/deliberation/live.py:729-874`

This task changes the function signature and internal behaviour but does NOT yet remove the interim call site (Task 6). After this task the interim call site still exists but now persists every brief — which is intentional setup; Task 6 will remove the interim call entirely.

- [ ] **Step 1: Read the function `_produce_live_secretary_brief`**

Run: `sed -n '720,880p' server/board/deliberation/live.py`
Note: parameters `is_final`, `last_member`; lines 856-857 conditional-persist; uses `format_live_secretary_brief(... brief_mode=..., is_final=...)`.

- [ ] **Step 2: Replace the function signature and prompt invocation**

In `server/board/deliberation/live.py`, locate the def line (currently around line 729) and the body lines that compute `brief_mode`, build the prompt, and persist.

Replace the function header from:

```python
    async def _produce_live_secretary_brief(
        self,
        *,
        session: BoardSession,
        user_query: str,
        messages: list[ConversationMessage],
        response_language: str,
        session_id: str,
        turn_index: int = 0,
        last_member=None,
        is_final: bool = False,
    ) -> None:
        """Summarise the live discussion via the Secretary agent.

        Called after **each** council member speaks (``is_final=False``) for
        incremental briefs, and once more at discussion end (``is_final=True``)
        for the comprehensive final executive brief.
        """
```

to:

```python
    async def _produce_live_secretary_brief(
        self,
        *,
        session: BoardSession,
        user_query: str,
        messages: list[ConversationMessage],
        response_language: str,
        session_id: str,
        round_index: int,
    ) -> None:
        """Summarise the live discussion via the Secretary agent (one call per round)."""
```

Then locate the lines that build `brief_mode` and call `format_live_secretary_brief`:

```python
        brief_mode = "FINAL" if is_final else f"INTERIM (after {last_member.title if last_member else f'turn #{turn_index}'})"

        self._emit({
            "event": "secretary_starting",
            "session_id": session_id,
            "member_id": secretary.id,
            "member_title": secretary.title,
            "turn_index": turn_index,
            "brief_mode": brief_mode,
            "is_final": is_final,
        })
```

Replace with:

```python
        self._emit({
            "event": "secretary_starting",
            "session_id": session_id,
            "member_id": secretary.id,
            "member_title": secretary.title,
            "round_index": round_index,
        })
```

Locate the prompt build:

```python
        prompt = format_live_secretary_brief(
            user_query=user_query,
            transcript=transcript,
            brief_mode=brief_mode,
            is_final=is_final,
        )
```

Replace with:

```python
        prompt = format_live_secretary_brief(
            user_query=user_query,
            transcript=transcript,
            round_index=round_index,
        )
```

Locate the message ID computation:

```python
        suffix = "final" if is_final else f"t{turn_index}"
        message_id = f"{session_id}_secretary_brief_{suffix}"
```

Replace with:

```python
        message_id = f"{session_id}_secretary_brief_r{round_index}"
```

Locate the per-event emissions for `secretary_delta` and `secretary_done` and remove the `is_final`, `brief_mode`, `turn_index` keys from those dicts; replace `turn_index` with `round_index`. The full `secretary_delta` payload becomes:

```python
                self._emit({
                    "event": "secretary_delta",
                    "session_id": session_id,
                    "message_id": message_id,
                    "member_id": secretary.id,
                    "member_title": secretary.title,
                    "round_index": round_index,
                    "delta": chunk.delta,
                    "content": brief_content,
                    "simulated_stream": chunk.simulated_stream,
                })
```

The full `secretary_done` payload becomes:

```python
        self._emit({
            "event": "secretary_done",
            "session_id": session_id,
            "message_id": message_id,
            "member_id": secretary.id,
            "member_title": secretary.title,
            "round_index": round_index,
            "content": brief_content,
            "model": final_model,
            "elapsed": elapsed,
            "finish_reason": finish_reason,
        })
```

Locate the persistence block (currently at lines ~856-865):

```python
        # Persist only the final brief on the session; interim ones are live-only
        if is_final:
            from .orchestrator import MemberResponse
            session.secretary_brief = MemberResponse(
                member_id=secretary.id,
                stage=4,
                content=brief_content,
                model=final_model,
                elapsed_seconds=elapsed,
            )
```

Replace with:

```python
        from .orchestrator import MemberResponse
        session.secretary_briefs.append(MemberResponse(
            member_id=secretary.id,
            stage=4,
            content=brief_content,
            model=final_model,
            elapsed_seconds=elapsed,
        ))
```

(Always persist; the caller controls how many times this runs.)

- [ ] **Step 3: Lower the secretary `max_tokens` ceiling to 1500**

In `_produce_live_secretary_brief`, locate (currently around live.py:778-779):

```python
        max_tokens = _resolve_live_turn_max_tokens(
            query_type=None,
            complexity=None,
        )
        # Give the secretary more room for structured output
        max_tokens = max(max_tokens, 3200)
```

Replace with:

```python
        max_tokens = _resolve_live_turn_max_tokens(
            query_type=None,
            complexity=None,
        )
        # Four-section bullet brief (≤80 lines × ~12 tokens/line) fits in 1500.
        max_tokens = max(max_tokens, 1500)
```

- [ ] **Step 4: Update the two existing call sites in `discuss()`**

In the same file, find the two existing calls. The first is at the top of the per-turn block (currently around line 432, inside the for-loop) — keep it for now, but update its arguments:

```python
            await self._produce_live_secretary_brief(
                session=session,
                user_query=user_query,
                messages=messages,
                response_language=response_language,
                session_id=session_id,
                round_index=session.continuation_count,
            )
```

The second call (currently around line 460, after the loop):

```python
        if messages and session.status == "awaiting_chair_decision":
            await self._produce_live_secretary_brief(
                session=session,
                user_query=user_query,
                messages=messages,
                response_language=response_language,
                session_id=session_id,
                round_index=session.continuation_count,
            )
```

(Both now use `round_index=session.continuation_count` since we are still in round 0 here. Task 6 deletes the first call.)

- [ ] **Step 5: Run the prompt + shape tests**

Run: `uv run pytest tests/test_secretary_brief_prompt.py tests/test_board_session_shape.py -v`
Expected: 11 tests PASS.

- [ ] **Step 6: Run the live-discussion contract test**

Run: `uv run pytest tests/test_live_discussion_contract.py -v --timeout=60`
Expected: PASS. (The contract test stubs `LiveBoardConversation` so refactor changes inside `_produce_live_secretary_brief` don't affect it directly; if a test name asserts `is_final` or `brief_mode` it must be updated — fix in place using the new field names.)

If any assertion still references `brief_mode` or `is_final`, edit the test to use `round_index` instead.

- [ ] **Step 7: Commit**

```bash
git add server/board/deliberation/live.py tests/
git commit -m "refactor(live): single-mode secretary brief with round_index

Drop is_final / brief_mode parameters. Each call now produces exactly
one brief and appends it to session.secretary_briefs. Caller chooses
when to invoke; this refactor does not yet change call frequency
(Task 6 removes the per-turn invocation).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Remove the per-turn interim Secretary brief call

**Files:**
- Modify: `server/board/deliberation/live.py:428-441` (delete the per-turn call)
- Create: `tests/test_live_secretary_single_brief.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_live_secretary_single_brief.py`:

```python
"""Verify that one live discussion produces exactly one Secretary brief."""

import unittest
from unittest.mock import AsyncMock, patch

from server.board.deliberation.live import LiveBoardConversation
from server.board.deliberation.orchestrator import BoardSession


class LiveSecretarySingleBriefTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_secretary_starting_event_emitted_per_turn(self) -> None:
        """secretary_starting/_delta/_done must fire ONCE per round, not per turn."""
        events: list[dict] = []

        def capture(event):
            events.append(event)

        conversation = LiveBoardConversation(on_event=capture, max_turns=3)

        # Patch _stream_member_message and _produce_live_secretary_brief to fast-stub
        # the inner loop without LLM calls.
        async def fake_member_msg(member, **_kwargs):
            from server.board.deliberation.live import ConversationMessage
            return ConversationMessage(
                id=f"msg_{member.id}",
                turn_index=1,
                member_id=member.id,
                member_title=member.title,
                role="member",
                content=f"{member.title} weighs in.",
            )

        async def fake_secretary_brief(*, session, user_query, messages, response_language, session_id, round_index):
            capture({"event": "secretary_done", "round_index": round_index})

        with patch.object(LiveBoardConversation, "_stream_member_message", new=fake_member_msg), \
             patch.object(LiveBoardConversation, "_produce_live_secretary_brief", new=fake_secretary_brief), \
             patch("server.board.deliberation.live.classify_query", new=AsyncMock()), \
             patch("server.board.deliberation.live.detect_shortcut", return_value=None):
            session = await conversation.discuss(
                "Should we ship X?",
                member_ids=["strategist", "architect", "critic"],
            )

        secretary_dones = [e for e in events if e.get("event") == "secretary_done"]
        self.assertEqual(
            len(secretary_dones), 1,
            f"expected exactly 1 secretary_done event in single-round meeting, got {len(secretary_dones)}: {secretary_dones}"
        )
        self.assertEqual(secretary_dones[0]["round_index"], 0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_live_secretary_single_brief.py -v`
Expected: FAIL — currently `_produce_live_secretary_brief` is called once per turn (3 turns + 1 final = 4 events), not once per round (1 event).

- [ ] **Step 3: Delete the per-turn interim call**

In `server/board/deliberation/live.py`, locate the block (currently around lines 428-441):

```python
            # ── Per-turn Secretary Brief ──────────────────────────────
            # After each council member finishes speaking, the Secretary
            # produces an incremental executive brief so the CEO can follow
            # the discussion in real time without reading raw transcripts.
            await self._produce_live_secretary_brief(
                session=session,
                user_query=user_query,
                messages=messages,
                response_language=response_language,
                session_id=session_id,
                round_index=session.continuation_count,
            )
```

Delete the entire block (the comment + the `await` call). The for-loop body now goes directly from `session.conversation["messages"].append(message.to_dict())` to `used_member_ids.add(member.id)`.

- [ ] **Step 4: Run the single-brief test to verify it passes**

Run: `uv run pytest tests/test_live_secretary_single_brief.py -v`
Expected: PASS — exactly 1 `secretary_done` event.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest tests/ -x --timeout=120`
Expected: All tests pass. If `test_live_discussion_contract.py` or any other test counted secretary events ≥ 2 it must be updated to expect 1.

- [ ] **Step 6: Commit**

```bash
git add server/board/deliberation/live.py tests/test_live_secretary_single_brief.py
git commit -m "feat(live): remove per-turn interim secretary brief

Eliminate the in-loop _produce_live_secretary_brief call. The Secretary
now runs exactly once per round (after the turn loop exits). For a
default 5-turn meeting this drops secretary LLM calls from 6 to 1.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Add `existing_session` resume + cap check + `meeting_capped` event

**Files:**
- Modify: `server/board/deliberation/live.py:208-260` (LiveBoardConversation.__init__) and `live.py:235-490` (discuss method)
- Modify: `tests/test_live_secretary_single_brief.py` (extend)

- [ ] **Step 1: Extend the test file**

Append to `tests/test_live_secretary_single_brief.py`:

```python
class LiveContinuationTest(unittest.IsolatedAsyncioTestCase):
    async def test_discuss_with_existing_session_bumps_continuation_count(self) -> None:
        events: list[dict] = []

        def capture(event):
            events.append(event)

        conversation = LiveBoardConversation(on_event=capture, max_turns=2)

        async def fake_member_msg(member, **_kwargs):
            from server.board.deliberation.live import ConversationMessage
            return ConversationMessage(
                id=f"msg_{member.id}_round{conversation._current_round}",
                turn_index=1,
                member_id=member.id,
                member_title=member.title,
                role="member",
                content=f"{member.title} weighs in.",
            )

        async def fake_secretary_brief(*, session, user_query, messages, response_language, session_id, round_index):
            from server.board.deliberation.orchestrator import MemberResponse
            session.secretary_briefs.append(MemberResponse(
                member_id="secretary", stage=4, content=f"brief r{round_index}",
                model="m", elapsed_seconds=0.1,
            ))
            capture({"event": "secretary_done", "round_index": round_index})

        with patch.object(LiveBoardConversation, "_stream_member_message", new=fake_member_msg), \
             patch.object(LiveBoardConversation, "_produce_live_secretary_brief", new=fake_secretary_brief), \
             patch("server.board.deliberation.live.classify_query", new=AsyncMock()), \
             patch("server.board.deliberation.live.detect_shortcut", return_value=None):
            # Round 0
            session = await conversation.discuss(
                "Should we ship X?",
                member_ids=["strategist", "architect"],
            )
            self.assertEqual(session.continuation_count, 0)
            self.assertEqual(len(session.secretary_briefs), 1)

            # Round 1 — continuation
            await conversation.discuss(
                "Follow-up: what about pricing?",
                member_ids=["strategist", "architect"],
                existing_session=session,
            )
            self.assertEqual(session.continuation_count, 1)
            self.assertEqual(len(session.secretary_briefs), 2)

    async def test_discuss_emits_meeting_capped_when_at_max_continuations(self) -> None:
        import os
        os.environ["AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS"] = "1"
        try:
            events: list[dict] = []
            conversation = LiveBoardConversation(on_event=events.append, max_turns=1)

            async def fake_member_msg(member, **_kwargs):
                from server.board.deliberation.live import ConversationMessage
                return ConversationMessage(id="m", turn_index=1, member_id=member.id,
                                          member_title=member.title, role="member", content="x")

            async def fake_secretary_brief(**kwargs):
                pass

            with patch.object(LiveBoardConversation, "_stream_member_message", new=fake_member_msg), \
                 patch.object(LiveBoardConversation, "_produce_live_secretary_brief", new=fake_secretary_brief), \
                 patch("server.board.deliberation.live.classify_query", new=AsyncMock()), \
                 patch("server.board.deliberation.live.detect_shortcut", return_value=None):
                session = await conversation.discuss("Q1", member_ids=["strategist"])
                # Force continuation count to the cap so the next call rejects.
                session.continuation_count = 1
                await conversation.discuss(
                    "Q2", member_ids=["strategist"], existing_session=session,
                )

            capped = [e for e in events if e.get("event") == "meeting_capped"]
            self.assertEqual(len(capped), 1)
            self.assertEqual(capped[0]["max_continuations"], 1)
        finally:
            os.environ.pop("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS", None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_live_secretary_single_brief.py::LiveContinuationTest -v`
Expected: FAIL — `discuss()` does not accept `existing_session` kwarg; cap check + `meeting_capped` event not implemented; `_current_round` attribute does not exist.

- [ ] **Step 3: Add an instance attribute to track the current round**

In `LiveBoardConversation.__init__` (around line 226), add at the end of the body:

```python
        self._current_round = 0
```

- [ ] **Step 4: Add `existing_session` and cap check to `discuss()`**

In `LiveBoardConversation.discuss()`, modify the signature to accept `existing_session`. Locate the current signature (around line 235):

```python
    async def discuss(
        self,
        user_query: str,
        *,
        member_ids: list[str] | None = None,
        skip_classify: bool = False,
        verify: bool = False,  # kept for endpoint symmetry; live verification is deferred
        session_id: str | None = None,
        clarification_answers: dict[str, Any] | None = None,  # reserved for parity
    ) -> BoardSession:
```

Add the new kwarg:

```python
    async def discuss(
        self,
        user_query: str,
        *,
        member_ids: list[str] | None = None,
        skip_classify: bool = False,
        verify: bool = False,  # kept for endpoint symmetry; live verification is deferred
        session_id: str | None = None,
        clarification_answers: dict[str, Any] | None = None,  # reserved for parity
        existing_session: BoardSession | None = None,
    ) -> BoardSession:
```

Then locate the current session-init block (around line 246-249):

```python
        del verify, clarification_answers
        session_id = session_id or f"board_{int(time.time())}"
        session = BoardSession(session_id=session_id, user_query=user_query)
        session.metrics = self.metrics
        session.status = "running"
```

Replace it with:

```python
        del verify, clarification_answers

        if existing_session is not None:
            session = existing_session
            session_id = session.session_id
            # Cap check before doing any work.
            if session.continuation_count >= self.max_continuations:
                self._emit({
                    "event": "meeting_capped",
                    "session_id": session_id,
                    "continuation_count": session.continuation_count,
                    "max_continuations": self.max_continuations,
                    "message": "Continuation cap reached. Adjourn to finalize.",
                })
                return session
            session.continuation_count += 1
            session.status = "running"
            self._current_round = session.continuation_count
            # Append the new CEO message to the conversation.
            session.conversation["messages"].append({
                "id": f"user_{len(session.conversation['messages'])}",
                "turn_index": len(session.conversation["messages"]),
                "member_id": self.chairperson.id,
                "member_title": "CEO / Chairperson",
                "role": "CEO",
                "speaker": "user",
                "content": user_query,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
        else:
            session_id = session_id or f"board_{int(time.time())}"
            session = BoardSession(session_id=session_id, user_query=user_query)
            session.metrics = self.metrics
            session.status = "running"
            self._current_round = 0
        self.metrics = session.metrics
```

- [ ] **Step 5: Update the `secretary_brief` round_index call sites**

In the same `discuss()` method, find the two remaining `_produce_live_secretary_brief` invocations (only the post-loop one survives after Task 6). Replace `round_index=session.continuation_count` with `round_index=self._current_round` so it stays consistent with the round counter set in step 4.

- [ ] **Step 6: Skip member-set re-selection when continuing**

In `discuss()`, locate the member-selection branches (currently around line 280-310 — the `if member_ids:` / `elif not skip_classify:` / `else:` chain that mutates `self.council`). Wrap the entire block so it runs only on round 0:

```python
        query_type = None
        complexity = None
        if existing_session is None:
            if member_ids:
                # ... existing manual-selection branch
                ...
            elif not skip_classify:
                # ... existing classifier branch
                ...
            else:
                # ... existing full-board branch
                ...
        else:
            # Reuse the council that was selected at meeting start.
            mode_reason = "Reusing council from meeting start (continuation)."
```

Concretely: leave the inner branch bodies (member-selection logic) untouched; only add the `if existing_session is None:` outer guard. Use the same indentation as the existing code; the `else` clause for the continuation case sets `mode_reason` so downstream `_build_participation_decisions` still has a string. Existing `self.council` was mutated on round 0 by `LiveBoardConversation.__init__` (or this code path); for continuations it stays as it was.

- [ ] **Step 7: Skip session-bootstrap when continuing**

Locate the conversation initialisation block (around line 328-340 — `session.conversation = {"messages": [...], ...}`). Wrap it with the same `if existing_session is None:` guard so we don't overwrite the existing transcript.

- [ ] **Step 8: Reset `used_member_ids` per round**

In `discuss()`, the for-loop over turns initialises `used_member_ids: set[str] = set()` near where the `for turn_index in range(...)` lives. Whether the round is initial or a continuation, this must be a fresh empty set at the top of each `discuss()` call. Read the surrounding code and confirm `used_member_ids` is a local variable that starts empty each call. If it does, no change needed. If it persists across calls (e.g. assigned to `self.`), make it local.

Run: `grep -n "used_member_ids" server/board/deliberation/live.py`
Expected: `used_member_ids` is a local variable of `discuss()`. If found assigned to `self.` anywhere, fix.

- [ ] **Step 9: Run the continuation tests**

Run: `uv run pytest tests/test_live_secretary_single_brief.py -v --timeout=60`
Expected: all tests PASS, including `LiveContinuationTest`.

- [ ] **Step 10: Run the full test suite**

Run: `uv run pytest tests/ -x --timeout=180`
Expected: all tests pass.

- [ ] **Step 11: Commit**

```bash
git add server/board/deliberation/live.py tests/test_live_secretary_single_brief.py
git commit -m "feat(live): support multi-round CEO discussion via existing_session

LiveBoardConversation.discuss() now accepts existing_session for
continuation rounds. On continuation it bumps continuation_count,
appends the new CEO message to the existing transcript, reuses the
council selected at meeting start, and re-runs the turn loop. When
continuation_count is already at AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS
(default 2) it emits meeting_capped and returns without running the
loop.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Add `POST /sessions/{session_id}/continue` endpoint

**Files:**
- Modify: `server/api/schemas.py`
- Modify: `server/api/routes/board.py`
- Create: `tests/test_continue_adjourn_endpoints.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_continue_adjourn_endpoints.py`:

```python
"""Contract tests for /sessions/{sid}/continue and /sessions/{sid}/adjourn."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from server.api.routes import board as board_routes
from server.api.schemas import ContinueRequest
from server.board.deliberation.orchestrator import BoardSession, MemberResponse


def _fake_request(client_ip: str = "127.0.0.1") -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sessions/test/continue",
        "headers": [],
        "client": (client_ip, 9999),
    })


class ContinueEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path("data/sessions").resolve()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = "board_99999"
        self.session_path = self.tmp_dir / f"{self.session_id}.json"
        # Seed a session in awaiting_chair_decision state.
        seed = {
            "session_id": self.session_id,
            "user_query": "Q1",
            "stage1": [],
            "stage2": [],
            "stage3": None,
            "secretary_brief": {"member_id": "secretary", "stage": 4, "content": "brief r0", "model": "m", "elapsed_seconds": 0.1},
            "secretary_briefs": [{"member_id": "secretary", "stage": 4, "content": "brief r0", "model": "m", "elapsed_seconds": 0.1}],
            "continuation_count": 0,
            "status": "awaiting_chair_decision",
            "conversation": {"messages": [{"id": "user_0", "speaker": "user", "content": "Q1"}], "routing_trace": []},
            "decision": None,
            "delegation_plan": None,
            "verification": None,
            "memory": None,
            "intake_cards": [],
            "clarification": {},
            "structured_output_warnings": [],
            "evidence_packets": {},
            "participation": [],
            "classification": None,
        }
        self.session_path.write_text(json.dumps(seed))

    def tearDown(self) -> None:
        if self.session_path.exists():
            self.session_path.unlink()
        board_routes._DELIBERATE_REQUESTS.clear()

    async def test_continue_unknown_session_returns_404(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id="board_does_not_exist",
                req=ContinueRequest(user_input="hello"),
                request=_fake_request(),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_continue_empty_user_input_returns_400(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id=self.session_id,
                req=ContinueRequest(user_input=""),
                request=_fake_request(),
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_continue_session_not_awaiting_returns_409(self) -> None:
        # Flip persisted status to running so the endpoint must reject.
        data = json.loads(self.session_path.read_text())
        data["status"] = "running"
        self.session_path.write_text(json.dumps(data))

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id=self.session_id,
                req=ContinueRequest(user_input="Follow up"),
                request=_fake_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_continue_at_cap_emits_meeting_capped_429(self) -> None:
        os.environ["AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS"] = "1"
        try:
            data = json.loads(self.session_path.read_text())
            data["continuation_count"] = 1  # already at cap
            self.session_path.write_text(json.dumps(data))

            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as ctx:
                await board_routes.continue_meeting(
                    session_id=self.session_id,
                    req=ContinueRequest(user_input="One more"),
                    request=_fake_request(),
                )
            self.assertEqual(ctx.exception.status_code, 429)
            detail = ctx.exception.detail
            if isinstance(detail, dict):
                self.assertEqual(detail.get("event"), "meeting_capped")
        finally:
            os.environ.pop("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS", None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_continue_adjourn_endpoints.py -v`
Expected: FAIL with `AttributeError: module 'server.api.schemas' has no attribute 'ContinueRequest'` and/or `AttributeError: module ... has no attribute 'continue_meeting'`.

- [ ] **Step 3: Add the schema**

In `server/api/schemas.py`, append:

```python
class ContinueRequest(BaseModel):
    user_input: str

class AdjournRequest(BaseModel):
    ceo_decision: str | None = None
```

(Use the same `BaseModel` import already present in the file. If the file uses Pydantic v1, both fields work as shown; if v2, no change needed.)

- [ ] **Step 4: Re-export the new schemas if `server/api/__init__.py` does explicit re-exports**

Run: `grep -n "QueryRequest\|FeedbackRequest" server/api/__init__.py`
If those names are explicitly imported / exported, append `ContinueRequest` and `AdjournRequest` to the same imports/exports. If the module re-exports via `from .schemas import *`, no change needed.

- [ ] **Step 5: Add the schemas to the top-of-file import block in board.py**

In `server/api/routes/board.py`, locate the existing imports near the top:

```python
from ..schemas import (
    FeedbackRequest,
    MemberInfo,
    QueryRequest,
    RoleGapReviewRequest,
    RoutingSignalRequest,
)
```

Replace with:

```python
from ..schemas import (
    AdjournRequest,
    ContinueRequest,
    FeedbackRequest,
    MemberInfo,
    QueryRequest,
    RoleGapReviewRequest,
    RoutingSignalRequest,
)
```

This makes the new request models resolvable as direct (non-string) type annotations in the route handlers below.

- [ ] **Step 6: Add the `continue_meeting` route handler**

In `server/api/routes/board.py`, add this handler. Place it directly above `@router.get("/sessions")` (around line 325 — the `/sessions` listing route) so the more-specific path is registered first per the existing ordering convention noted in board.py comments.

```python
@router.post("/sessions/{session_id:path}/continue")
async def continue_meeting(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: ContinueRequest = ...,  # type: ignore[assignment]
    request: Request = ...,  # type: ignore[assignment]
):
    """Resume a meeting waiting on the CEO with a follow-up message."""
    _enforce_deliberate_rate_limit(request)
    _validate_session_id(session_id)

    if not req.user_input or not req.user_input.strip():
        raise HTTPException(400, detail="user_input must be non-empty")

    session_path = None
    for dirname in ("data/sessions", "data/conversations"):
        candidate = FilePath(f"{dirname}/{session_id}.json")
        if candidate.exists():
            session_path = candidate
            break
    if session_path is None:
        raise HTTPException(404, detail="Session not found")

    data = json.loads(session_path.read_text())
    if data.get("status") != "awaiting_chair_decision":
        raise HTTPException(
            409,
            detail=f"Session is in status '{data.get('status')}'; cannot continue.",
        )

    # Re-hydrate BoardSession from persisted JSON.
    from server.board.deliberation.orchestrator import BoardSession, MemberResponse

    def _resp_from_dict(d: dict | None) -> MemberResponse | None:
        if not d:
            return None
        return MemberResponse(
            member_id=d["member_id"], stage=d["stage"], content=d["content"],
            model=d["model"], elapsed_seconds=d["elapsed_seconds"],
        )

    session = BoardSession(session_id=data["session_id"], user_query=data["user_query"])
    session.continuation_count = int(data.get("continuation_count", 0))
    session.secretary_briefs = [
        _resp_from_dict(b) for b in (data.get("secretary_briefs") or []) if b is not None
    ]
    session.conversation = data.get("conversation") or {"messages": [], "routing_trace": []}
    session.status = data.get("status", "awaiting_chair_decision")
    # (Other fields like stage1/stage2/stage3 are not required for live continuation.)

    # Cap check happens both here (for HTTP semantics) and inside discuss() (for direct callers).
    max_continuations = _positive_int_env("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS", 2)
    if session.continuation_count >= max_continuations:
        raise HTTPException(
            status_code=429,
            detail={
                "event": "meeting_capped",
                "session_id": session_id,
                "continuation_count": session.continuation_count,
                "max_continuations": max_continuations,
                "message": "Continuation cap reached. Adjourn to finalize.",
            },
        )

    queue: asyncio.Queue[dict] = asyncio.Queue()

    def on_event(event: dict) -> None:
        queue.put_nowait(event)

    async def event_generator():
        conversation = LiveBoardConversation(on_event=on_event)
        task = asyncio.create_task(
            conversation.discuss(
                req.user_input,
                existing_session=session,
            )
        )

        try:
            while True:
                if task.done():
                    while not queue.empty():
                        event = queue.get_nowait()
                        yield f"data: {json.dumps(event)}\n\n"
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

            try:
                resumed = task.result()
                # Persist the updated session so a subsequent /continue or /adjourn sees it.
                resumed.save()
                yield f"data: {json.dumps({'event': 'complete', 'session': resumed.to_dict()})}\n\n"
            except Exception as e:
                payload = _public_error_payload(e, default_code="unexpected_error")
                yield f"data: {json.dumps({'event': 'error', **payload})}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

Notes on the imports already at the top of the file:
- `HTTPException`, `Path`, `Request`, `StreamingResponse`, `asyncio`, `json` are imported.
- `LiveBoardConversation` is imported.
- `_enforce_deliberate_rate_limit`, `_validate_session_id`, `_positive_int_env`, `_public_error_payload` are local helpers in the same file.
- `FilePath` is the existing alias for `pathlib.Path`.

If `_validate_session_id` is not defined in `board.py`, search for its definition (`grep -n "_validate_session_id" server/api/routes/board.py`); if the existing /sessions sub-routes call it, it exists. If not, copy the equivalent regex check inline.

- [ ] **Step 7: Run the endpoint tests**

Run: `uv run pytest tests/test_continue_adjourn_endpoints.py::ContinueEndpointTest -v --timeout=60`
Expected: 4 ContinueEndpointTest tests PASS.

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest tests/ -x --timeout=180`
Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add server/api/schemas.py server/api/routes/board.py server/api/__init__.py tests/test_continue_adjourn_endpoints.py 2>/dev/null; git add server/api/schemas.py server/api/routes/board.py tests/test_continue_adjourn_endpoints.py
git commit -m "feat(api): POST /sessions/{sid}/continue resumes live meeting

New endpoint loads a session from disk, validates status =
awaiting_chair_decision and continuation_count < cap, and streams a
new SSE round through LiveBoardConversation.discuss(existing_session=).
Errors: 404 unknown, 400 empty input, 409 wrong status, 429 cap hit
(detail.event = meeting_capped).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Add `POST /sessions/{session_id}/adjourn` endpoint

**Files:**
- Modify: `server/api/routes/board.py`
- Modify: `tests/test_continue_adjourn_endpoints.py` (extend)

- [ ] **Step 1: Extend the test file**

Append to `tests/test_continue_adjourn_endpoints.py`:

```python
class AdjournEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path("data/sessions").resolve()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = "board_88888"
        self.session_path = self.tmp_dir / f"{self.session_id}.json"
        self.session_path.write_text(json.dumps({
            "session_id": self.session_id,
            "user_query": "Q1",
            "status": "awaiting_chair_decision",
            "continuation_count": 1,
            "secretary_brief": {"member_id": "secretary", "stage": 4, "content": "b", "model": "m", "elapsed_seconds": 0.1},
            "secretary_briefs": [{"member_id": "secretary", "stage": 4, "content": "b", "model": "m", "elapsed_seconds": 0.1}],
            "conversation": {"messages": [], "routing_trace": []},
            "stage1": [], "stage2": [], "stage3": None,
            "decision": None, "delegation_plan": None, "verification": None, "memory": None,
            "intake_cards": [], "clarification": {}, "structured_output_warnings": [],
            "evidence_packets": {}, "participation": [], "classification": None,
        }))

    def tearDown(self) -> None:
        if self.session_path.exists():
            self.session_path.unlink()

    async def test_adjourn_unknown_session_returns_404(self) -> None:
        from fastapi import HTTPException
        from server.api.schemas import AdjournRequest
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.adjourn_meeting(
                session_id="board_does_not_exist",
                req=AdjournRequest(),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_adjourn_marks_session_adjourned(self) -> None:
        from server.api.schemas import AdjournRequest
        result = await board_routes.adjourn_meeting(
            session_id=self.session_id,
            req=AdjournRequest(ceo_decision="Ship it."),
        )
        self.assertEqual(result["status"], "adjourned")
        self.assertEqual(result["session_id"], self.session_id)

        # Verify the persisted file reflects the new status.
        persisted = json.loads(self.session_path.read_text())
        self.assertEqual(persisted["status"], "adjourned")

    async def test_adjourn_idempotent(self) -> None:
        from server.api.schemas import AdjournRequest
        first = await board_routes.adjourn_meeting(session_id=self.session_id, req=AdjournRequest())
        second = await board_routes.adjourn_meeting(session_id=self.session_id, req=AdjournRequest())
        self.assertEqual(first["status"], "adjourned")
        self.assertEqual(second["status"], "adjourned")

    async def test_adjourn_rejects_running_session(self) -> None:
        data = json.loads(self.session_path.read_text())
        data["status"] = "running"
        self.session_path.write_text(json.dumps(data))

        from fastapi import HTTPException
        from server.api.schemas import AdjournRequest
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.adjourn_meeting(session_id=self.session_id, req=AdjournRequest())
        self.assertEqual(ctx.exception.status_code, 409)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_continue_adjourn_endpoints.py::AdjournEndpointTest -v`
Expected: FAIL with `AttributeError: 'adjourn_meeting'`.

- [ ] **Step 3: Add the route handler**

In `server/api/routes/board.py`, immediately after the `continue_meeting` handler from Task 8, add:

```python
@router.post("/sessions/{session_id:path}/adjourn")
async def adjourn_meeting(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: AdjournRequest = ...,  # type: ignore[assignment]
):
    """Mark a meeting adjourned. Idempotent."""
    _validate_session_id(session_id)

    session_path = None
    for dirname in ("data/sessions", "data/conversations"):
        candidate = FilePath(f"{dirname}/{session_id}.json")
        if candidate.exists():
            session_path = candidate
            break
    if session_path is None:
        raise HTTPException(404, detail="Session not found")

    data = json.loads(session_path.read_text())
    current_status = data.get("status")

    # Idempotent: already-adjourned sessions are returned as-is.
    if current_status == "adjourned":
        return {
            "session_id": session_id,
            "status": "adjourned",
            "final_brief": data.get("secretary_brief"),
        }

    if current_status != "awaiting_chair_decision":
        raise HTTPException(
            409,
            detail=f"Session is in status '{current_status}'; can only adjourn from 'awaiting_chair_decision'.",
        )

    if req.ceo_decision and req.ceo_decision.strip():
        messages = data.setdefault("conversation", {"messages": [], "routing_trace": []}).setdefault("messages", [])
        messages.append({
            "id": f"user_{len(messages)}",
            "turn_index": len(messages),
            "member_id": "chairperson",
            "member_title": "CEO / Chairperson",
            "role": "CEO",
            "speaker": "user",
            "content": req.ceo_decision.strip(),
        })

    data["status"] = "adjourned"
    session_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    return {
        "session_id": session_id,
        "status": "adjourned",
        "final_brief": data.get("secretary_brief"),
    }
```

- [ ] **Step 4: Run the adjourn tests**

Run: `uv run pytest tests/test_continue_adjourn_endpoints.py::AdjournEndpointTest -v --timeout=30`
Expected: 4 AdjournEndpointTest tests PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -x --timeout=180`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/api/routes/board.py tests/test_continue_adjourn_endpoints.py
git commit -m "feat(api): POST /sessions/{sid}/adjourn closes a live meeting

Idempotent endpoint that flips a session from awaiting_chair_decision
to adjourned. Optionally appends a CEO decision message to the
conversation transcript before persisting. Returns 404 for unknown
sessions, 409 if status != awaiting_chair_decision (other than the
already-adjourned no-op), 200 otherwise.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Update frontend types

**Files:**
- Modify: `ui/src/shared/types.ts`

- [ ] **Step 1: Read the current types**

Run: `grep -n "Secretary\|secretary_brief\|brief_mode\|is_final\|MeetingCapped\|continuation_count" ui/src/shared/types.ts`
Note the lines that define `SecretaryBrief`, the SSE event union (likely `LiveDiscussionEvent` or similar), and the `BoardSession` shape.

- [ ] **Step 2: Add `MeetingCapped` event variant and round-indexed Secretary event**

In `ui/src/shared/types.ts`, locate the union of SSE event types. Find the existing entries for `secretary_starting`, `secretary_delta`, `secretary_done`, `secretary_failed` and update each:

```typescript
type SecretaryStartingEvent = {
  event: 'secretary_starting';
  session_id: string;
  member_id: string;
  member_title: string;
  round_index: number;
};

type SecretaryDeltaEvent = {
  event: 'secretary_delta';
  session_id: string;
  message_id: string;
  member_id: string;
  member_title: string;
  round_index: number;
  delta: string;
  content: string;
  simulated_stream?: boolean;
};

type SecretaryDoneEvent = {
  event: 'secretary_done';
  session_id: string;
  message_id: string;
  member_id: string;
  member_title: string;
  round_index: number;
  content: string;
  model: string;
  elapsed: number;
  finish_reason?: string;
};

type SecretaryFailedEvent = {
  event: 'secretary_failed';
  session_id: string;
  member_id: string;
  round_index: number;
  error: string;
};

type MeetingCappedEvent = {
  event: 'meeting_capped';
  session_id: string;
  continuation_count: number;
  max_continuations: number;
  message: string;
};
```

(Drop any `is_final?: boolean` and `brief_mode?: string` fields from the existing event types and replace `turn_index?: number` with `round_index: number`. Add `MeetingCappedEvent` to the union type that ties all live events together.)

- [ ] **Step 3: Update the `BoardSession` shape**

Find `interface BoardSession` (or `type BoardSession`). Add:

```typescript
  continuation_count: number;
  secretary_briefs: SecretaryBrief[];
```

Keep the existing `secretary_brief?: SecretaryBrief | null;` for back-compat — it now mirrors the latest entry in `secretary_briefs`.

- [ ] **Step 4: Drop `Secretary-Interim` role; rename to `Secretary`**

Search for `'Secretary-Interim'` and `'Secretary-Final'` literals across `ui/src/`:

Run: `grep -rn "Secretary-Interim\|Secretary-Final" ui/src/`

Each location must be updated. In `types.ts`, if the role is part of a `MessageRole` union, replace `'Secretary-Interim' | 'Secretary-Final'` with just `'Secretary'`.

- [ ] **Step 5: Type-check the frontend**

Run: `cd ui && npx tsc --noEmit`
Expected: PASS. (If there are type errors in `App.tsx`, those will be fixed in Task 11. Allow only `App.tsx` errors here; fail the step if any other file errors.)

- [ ] **Step 6: Commit**

```bash
git add ui/src/shared/types.ts
git commit -m "types(ui): drop interim secretary, add round_index + meeting_capped

Replace is_final/brief_mode dimensions with round_index on all
secretary_* events. Add MeetingCappedEvent to the live event union.
Add continuation_count and secretary_briefs[] to BoardSession; the
single secretary_brief field stays as a back-compat alias for the
latest brief.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Update App.tsx — drop interim render, add follow-up + adjourn UI

**Files:**
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Read the current secretary handlers + chair-decision branch**

Run: `grep -n "secretary_starting\|secretary_delta\|secretary_done\|chair_decision_required\|Secretary-Interim\|Secretary-Final\|Adjourn\|continuation_count" ui/src/App.tsx`
Note the exact line ranges to edit.

- [ ] **Step 2: Drop interim role, render only "Secretary"**

For each of `secretary_starting`, `secretary_delta`, `secretary_done` handlers, locate the `role: isFinal ? 'Secretary-Final' : 'Secretary-Interim'` ternary and replace with the literal `role: 'Secretary'`. Drop the `isFinal` local computation entirely from those handlers. Remove any `brief_mode` references.

- [ ] **Step 3: Replace `pushLiveFeed` text that mentioned interim/final with round-index labels**

Where the existing handlers wrote `Secretary preparing ${briefMode.toLowerCase()} executive brief…`, replace with `Secretary preparing brief for round ${data.round_index}…` and similar for `secretary_done`.

- [ ] **Step 4: Add follow-up + adjourn UI on `chair_decision_required`**

Locate the existing `chair_decision_required` handler. Below it (or in the JSX render path it triggers), add a new component that lets the CEO either send a follow-up or adjourn. The minimum viable shape is two buttons + a textarea, conditionally rendered when `tableStatus.label === 'CEO decision'` (or whatever the existing CEO-decision indicator is).

Add this component near the top of `App.tsx` (after imports):

```typescript
type FollowupBarProps = {
  sessionId: string;
  continuationCount: number;
  maxContinuations: number;
  onSendFollowup: (text: string) => void;
  onAdjourn: (decisionText: string) => void;
};

function FollowupBar({ sessionId, continuationCount, maxContinuations, onSendFollowup, onAdjourn }: FollowupBarProps) {
  const [text, setText] = useState('');
  const atCap = continuationCount >= maxContinuations;
  return (
    <div className="followup-bar">
      <textarea
        value={text}
        placeholder={atCap
          ? `Continuation cap reached (${continuationCount}/${maxContinuations}). Adjourn to finalize.`
          : 'Send a follow-up to the board…'}
        onChange={(e) => setText(e.target.value)}
        rows={3}
      />
      <div className="followup-bar__actions">
        <button
          type="button"
          disabled={atCap || !text.trim()}
          onClick={() => { onSendFollowup(text.trim()); setText(''); }}
        >
          Send follow-up
        </button>
        <button
          type="button"
          onClick={() => { onAdjourn(text.trim()); setText(''); }}
        >
          Adjourn
        </button>
      </div>
    </div>
  );
}
```

Then wire two handler callbacks at the App level:

```typescript
async function sendFollowup(text: string) {
  if (!sessionId) return;
  setActiveStreamMessageId(null); // close prior stream visual cue
  const resp = await fetch(`/sessions/${encodeURIComponent(sessionId)}/continue`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_input: text }),
  });
  if (!resp.ok) {
    pushLiveFeed({ kind: 'failed', text: `Follow-up rejected (${resp.status})` });
    return;
  }
  // The existing SSE-handler code path consumes events from the response body.
  // Hook into the same handler used for /deliberate/stream.
  await consumeSseStream(resp);
}

async function adjournMeeting(decisionText: string) {
  if (!sessionId) return;
  const resp = await fetch(`/sessions/${encodeURIComponent(sessionId)}/adjourn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ceo_decision: decisionText || undefined }),
  });
  if (resp.ok) {
    setTableStatus({ label: 'Adjourned', title: 'Meeting closed' });
  } else {
    pushLiveFeed({ kind: 'failed', text: `Adjourn rejected (${resp.status})` });
  }
}
```

If `consumeSseStream` does not yet exist in `App.tsx`, factor out the existing SSE event-consumption loop (the one used by the initial `/deliberate/stream` POST) into a function with that name and call it from both the initial start and the new follow-up. If extraction is complex, inline the event loop into `sendFollowup` so behaviour matches the initial round.

Render the bar inside the conversation area, gated on `tableStatus.label === 'CEO decision'` (or equivalent):

```tsx
{tableStatus.label === 'CEO decision' && sessionId && (
  <FollowupBar
    sessionId={sessionId}
    continuationCount={session?.continuation_count ?? 0}
    maxContinuations={maxContinuations}
    onSendFollowup={sendFollowup}
    onAdjourn={adjournMeeting}
  />
)}
```

Source `maxContinuations` from `import.meta.env.VITE_MAX_CONTINUATIONS` (defaulting to `2`) or hardcode `2` for parity with the server default.

- [ ] **Step 5: Handle `meeting_capped` event**

In the SSE event switch, add a branch alongside the existing `secretary_failed` branch:

```typescript
if (data.event === 'meeting_capped') {
  pushLiveFeed({
    kind: 'failed',
    text: `Continuation cap reached (${data.continuation_count}/${data.max_continuations}). Adjourn to finalize.`,
  });
  setTableStatus({ label: 'CEO decision', title: 'Cap reached — adjourn' });
  return;
}
```

- [ ] **Step 6: Type-check + manual smoke**

Run: `cd ui && npx tsc --noEmit`
Expected: PASS.

Run: `./start.sh` and open `http://localhost:8000` in a browser. Drive a 3-round meeting:
1. Type a question, send → wait for first Secretary brief.
2. Click "Send follow-up" with a new question → wait for second Secretary brief.
3. Click "Send follow-up" again with a third question → wait for third Secretary brief.
4. Click "Send follow-up" once more → expect cap event, "Send follow-up" disabled.
5. Click "Adjourn" → meeting marked closed.

Confirm in the conversation log: exactly one Secretary entry per round (3 total, no `Secretary-Interim`).

- [ ] **Step 7: Commit**

```bash
git add ui/src/App.tsx
git commit -m "feat(ui): follow-up + adjourn UI for multi-round CEO meetings

Drop the Secretary-Interim render path. After chair_decision_required,
show a follow-up bar with a textarea, 'Send follow-up' (disabled at
cap), and 'Adjourn' buttons. Send follow-up POSTs to
/sessions/{sid}/continue and consumes the resulting SSE stream;
Adjourn POSTs to /sessions/{sid}/adjourn. Handle meeting_capped event
by disabling further follow-ups.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: End-to-end verification + token-usage check

**Files:** none (verification step)

- [ ] **Step 1: Run the full backend suite**

Run: `uv run pytest tests/ --timeout=300`
Expected: 0 failures.

- [ ] **Step 2: Run a token-cost comparison**

The spec acceptance criterion is a ≥ 40 % token reduction on an equivalent 5-turn single-round meeting.

Run: `uv run python -m server.cli --members strategist,architect,critic,product,researcher --budget "Should we ship feature X next quarter?"`
Note the reported total tokens.

If you have a pre-fix branch tag (e.g. `pre-secretary-fix`) checked out for comparison, run the same command there and diff. If not, the absolute count after the fix should be visibly smaller than the same query on staged mode (which already calls Secretary once); use the staged-mode total as the lower-bound reference and confirm the live-mode total is now within ~10 % of staged.

Record the numbers in the commit message of the next step.

- [ ] **Step 3: Manual UI walkthrough**

Run: `./start.sh`, open the UI in a browser. Run the 3-round + cap + adjourn flow described in Task 11 step 6. Confirm:

- One Secretary entry per round (no `Secretary-Interim` role anywhere in the conversation log).
- Each Secretary brief has only the four allowed headers (Agreements / Conflicts / Open Questions / Decision Needed From CEO), each with bullets.
- "Send follow-up" disables at cap; "Adjourn" works at any awaiting-CEO checkpoint.
- After "Adjourn", the UI shows "Adjourned" status and inputs are hidden.

- [ ] **Step 4: Mark verification complete**

Update the spec status header from "Approved (brainstormed) — ready for implementation plan" to "Implemented".

In `docs/superpowers/specs/2026-05-03-secretary-flow-multiround-design.md`, change:

```
**Status:** Approved (brainstormed) — ready for implementation plan
```

to:

```
**Status:** Implemented
```

- [ ] **Step 5: Final commit**

```bash
git add docs/superpowers/specs/2026-05-03-secretary-flow-multiround-design.md
git commit -m "docs(spec): mark secretary multi-round design implemented

All 12 tasks complete: per-turn secretary brief removed, four-section
bullet template live, /continue + /adjourn endpoints shipped, frontend
follow-up bar in place. Token cost on equivalent 5-turn meeting:
[record actual reduction here].

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Spec Coverage Map

| Spec section | Implementing task(s) |
|---|---|
| Goal 1 — eliminate interim briefs | Task 6 |
| Goal 2 — four-section bullet output | Tasks 1, 2, 3 |
| Goal 3 — multi-round CEO loop | Tasks 7, 8, 9, 11 |
| Decision: keep current member-selection UI | Task 7 step 6 (skip re-selection on continue) |
| Decision: continuous conversation, no rigid round semantics | Task 7 step 7 (no transcript reset), Task 11 (textarea, no round picker) |
| Decision: 4-section format | Tasks 1, 3 |
| Decision: hard cap + adjourn button | Tasks 7, 8, 9, 11 |
| Architecture: stateless HTTP per round | Tasks 8, 9 |
| Data flow: `continuation_count`, `secretary_briefs[]`, status enum | Task 4 |
| Data flow: per-round state transitions | Tasks 7 (in-memory), 8 (load/persist), 9 (adjourn persist) |
| Data flow: full transcript per round | Task 7 step 7 (no reset), Task 5 (transcript hand-off unchanged) |
| Data flow: reset `used_member_ids` per round | Task 7 step 8 |
| API: existing /deliberate/stream — only one secretary event | Task 6 |
| API: `/sessions/{sid}/continue` | Task 8 |
| API: `/sessions/{sid}/adjourn` | Task 9 |
| API: cap behaviour (429 + meeting_capped) | Task 7 (in-process), Task 8 (HTTP) |
| Secretary template: 4 sections + caps | Tasks 1, 3 |
| Secretary template: max_tokens lowered to 1500 | Task 5 — change `max(max_tokens, 3200)` to `max(max_tokens, 1500)` while editing the function (note this in step 2 of Task 5 if you find that line; if not, add a follow-up step inside Task 5 to do it) |
| Code locus: `server/board/deliberation/live.py` | Tasks 5, 6, 7 |
| Code locus: `server/board/deliberation/prompts.py` | Task 3 |
| Code locus: `server/members/secretary.md` | Task 1 |
| Code locus: `server/board/projection.py` | Task 4 step 6 adds `secretary_briefs` and `continuation_count` to the `adapt_session_record` output. |
| Code locus: `server/api/` | Tasks 8, 9 |
| Code locus: `ui/src/shared/types.ts` | Task 10 |
| Code locus: `ui/src/App.tsx` | Task 11 |
| Tests: unit + integration | Tasks 2, 4, 6, 7, 8, 9 |
| Verification | Task 12 |

## Notes for the Executor

- **TDD discipline.** For every task with a test, run the test BEFORE writing implementation. The failing test confirms you are testing the right behaviour. The passing test confirms you implemented it.
- **Frequent commits.** Each task ends with a commit. Do not batch tasks into a single commit.
- **Don't skip steps.** "Run the full test suite" steps catch regressions early; skipping them lets bugs accumulate.
- **If a step is blocked** (e.g. an assumption proves wrong on inspection), STOP and surface the blocker rather than improvising. The plan's correctness depends on each step landing as written.
