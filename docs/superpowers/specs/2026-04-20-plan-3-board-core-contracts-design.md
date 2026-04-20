# Plan 3 — Board Core Contracts (Cluster C)

**Status:** proposed
**Date:** 2026-04-20
**Owner:** TBD
**Related review:** commit 8906ae9 post-review, items P1.5 (hardcoded member IDs), P1.6 (structured Stage 1/2)
**Dependencies:** none
**Parallelizable with:** Plans 1, 2, 5
**Blocks:** Plan 4 (web search injection shares Stage 1 prompt surface)
**Estimated scope:** medium (~5 core files + every `members/*.md`, ~250 LOC)

## Goal

Eliminate two fragility sources in the board core:

1. Member-specific intake behavior is a **dict literal** inside
   `server/board/deliberation/orchestrator.py`. Any member id rename or new
   member silently breaks intake clarification.
2. Stage 1 and Stage 2 inter-stage compaction relies on **regex scraping of
   markdown headers** (`## TL;DR`, `## Recommendation`, etc.). Any model
   drift in header formatting silently yields empty sections and a skeleton
   Stage 2 review; we have no alarm for this failure mode.

## Scope

### In scope
- **#5** Move per-member intake defaults (`clarifying_question`,
  `immediate_concern`, `proposed_path`, `required_execution_unit`) and the
  ambiguous-term list from `_should_pause_for_clarification` into
  member markdown frontmatter and/or `roster.yaml`.
- **#6** Enforce structured output on Stage 1 and Stage 2 via Pydantic
  schemas + JSON fenced block; keep regex compaction as fallback path.
- Warning surfaced to the session when fallback is used (instrument drift).

### Out of scope
- Classifier prompt redesign.
- Chairman Stage 3 output schema (intentional — Stage 3 is a decision
  document consumed by humans/Hermes, not compacted).
- Delegation plan JSON (already structured; not touched here).
- Any new web-search wiring (Plan 4).

## Files touched
- `server/members/*.md` — add `intake:` frontmatter block
- `server/board/roster/roster.yaml` — add `ambiguity_triggers` list
- `server/board/loader.py` — parse `intake` frontmatter into `BoardMember`
- `server/board/config.py` — add `intake` field to `BoardMember` dataclass
- `server/board/deliberation/orchestrator.py` — `_build_intake_card` reads
  from member object; `_should_pause_for_clarification` reads roster trigger list
- `server/board/deliberation/prompts.py` — Stage 1/2 prompts request JSON
- `server/board/deliberation/compaction.py` — JSON parser first, regex fallback
- (new) `server/board/deliberation/structured.py` — Pydantic schemas for
  Stage 1/2 outputs
- `tests/test_first_member_contract.py`, `test_protocol_contract.py`,
  `test_context_compaction_contract.py` — extend
- (new) `tests/test_member_intake_frontmatter_contract.py`

## Phase 0 — Reproduce before code

Commit failing tests first.

1. **Hardcoded-id detector:**
   ```python
   def test_orchestrator_has_no_hardcoded_member_ids():
       import pathlib, re
       text = pathlib.Path("server/board/deliberation/orchestrator.py").read_text()
       for mid in ("strategist", "product", "researcher",
                   "critic", "architect", "builder"):
           assert re.search(rf'["\']{mid}["\']', text) is None, \
               f"orchestrator still hardcodes member id: {mid}"
   ```
   Fails today: literals exist in `_build_intake_card` and `_should_pause_for_clarification`.

2. **Drifted-format compaction:**
   ```python
   def test_stage1_compaction_survives_header_drift():
       drifted = "**TL;DR:** alpha\n\n**Recommendation:** beta\n"
       from server.board.deliberation.compaction import _compact_single_stage1
       out = _compact_single_stage1(drifted)
       assert "alpha" in out and "beta" in out
   ```
   Fails today: regex matches `^## TL;DR$` only.

3. **Missing intake frontmatter fails contract:**
   ```python
   def test_all_council_members_have_intake_frontmatter():
       # load members; every non-shelved, non-chairperson member
       # must have all four intake fields populated
   ```
   Fails today: `BoardMember` has no `intake` attribute.

## Implementation steps

### Step 1 — Schema
- Add dataclass `MemberIntake` in `server/board/config.py` with four string
  fields and an optional `unit`.
- Extend `BoardMember` with `intake: MemberIntake | None = None`.

### Step 2 — Member markdown updates
- For each council member (NOT the chairperson — chair does not appear in
  `BoardOrchestrator.council` and is not passed through `stage0_intake`),
  i.e. `strategist`, `product`, `researcher`, `critic`, `architect`,
  `builder`, add frontmatter block:
  ```yaml
  intake:
    clarifying_question: "..."
    immediate_concern: "..."
    proposed_path: "..."
    required_execution_unit: "strategy"
  ```
- Copy current hardcoded values from `_build_intake_card` verbatim to avoid
  behavioral drift.

### Step 3 — Loader
- `loader.load_members` parses `intake:` block into `MemberIntake`.
- Contract: if frontmatter missing `intake`, loader raises `MemberLoadError`
  listing the member id.
- Update `test_first_member_contract.py` fixture members as needed.

### Step 4 — Roster triggers
- Move `{"business", "product", "ai", "search", "e-commerce", "ecommerce"}`
  and the gating member-id set `{"product", "researcher", "strategist", "architect"}`
  into `roster.yaml`:
  ```yaml
  clarification_gate:
    gating_member_capabilities: ["product_strategy", "user_research",
                                  "market_strategy", "technical_feasibility"]
    ambiguous_terms: [business, product, ai, search, e-commerce, ecommerce]
    min_terms_present: 2
    max_query_words: 14
  ```
- `_should_pause_for_clarification` reads from roster, checks by capability
  (not member id), so future renames do not break the gate.

### Step 5 — Orchestrator refactor
- `_build_intake_card(member, user_query, *, blocking)` returns a dict
  derived entirely from `member.intake` plus live fields; no dict literal.
- `_should_pause_for_clarification` uses the roster config.

### Step 6 — Structured Stage 1/2
- New module `deliberation/structured.py` with Pydantic:
  ```python
  class Stage1Response(BaseModel):
      confidence: Literal["High", "Medium", "Low"]
      tldr: str
      analysis: str
      recommendation: str
      risks: list[Risk]
      open_questions: list[str]
  class Stage2Response(BaseModel):
      confidence: Literal["High", "Medium", "Low"]
      updated_position: str
      peer_challenges: list[str]
      ranking: list[str]
  ```
- Stage 1/2 prompt update: require JSON inside a single fenced block
  labeled ```json with the schema attached inline.
- `compact_stage1_responses`:
  1. Find fenced ```json block, parse into `Stage1Response`; if success,
     project to compacted dict.
  2. On parse failure: emit structured-output warning onto session, fall
     back to existing regex compaction (unchanged).
- `compact_stage2_responses`: same pattern.

### Step 7 — Warning plumbing
- `BoardSession.structured_output_warnings` already exists; append
  `"stage1_json_parse_failed:{member_id}"` when fallback fires.
- `on_structured_output_warning` callback already wired via SSE.

## Test strategy

- **Unit:**
  - `test_member_intake_frontmatter_contract.py` asserts every active member
    loads an `intake` object with four non-empty fields.
  - `test_orchestrator_has_no_hardcoded_member_ids` from Phase 0.
  - `test_stage1_compaction_survives_header_drift` (fallback path).
  - `test_stage1_json_structured_output_preferred` (JSON parse path).
- **Contract:** `test_protocol_contract.py` extended — Stage 1/2 prompts
  include the fenced-JSON schema instruction.
- **Integration:** existing `test_adaptive_routing_contract.py` run with a
  fake LLM that emits drifted markdown; assert warning appended, compaction
  still yields non-empty peer-review payload.
- **Golden tests:** `test_context_compaction_contract.py` — both a
  schema-conforming JSON input and the historical markdown input produce
  semantically-equivalent compacted output.
- **Smoke:** `uv run python -m server.cli "Should we build X?"` against a
  fake provider fixture — deliberation completes end-to-end with structured
  outputs.
- **Edge:**
  - Model emits JSON wrapped in ```json``` with leading prose → still parsed
    (extract fence, ignore preamble).
  - Model emits JSON missing `risks` → Pydantic raises, fallback fires,
    warning recorded.

## Cross-cutting execution policy

Same as Plan 1. Highlights:
1. Phase 0 failing tests committed first.
2. Keep behavior identical if the model still emits old-format markdown.
   Structured output is preferred but not required — this is an additive
   robustness change, not a breaking contract.
3. No new framework: Pydantic is already a dependency.
4. 3-attempt cap on any failing step → reset to last green commit.

## Sub-agent assignments

- **Explore** agent — exhaustive pass over every `server/members/*.md`,
  every caller of `_build_intake_card` / `_should_pause_for_clarification`,
  every caller of `compact_stage1_responses` / `compact_stage2_responses`,
  and any test using fake Stage 1 outputs. Thoroughness: `very thorough`.
- **general-purpose** — implementer.
- **superpowers:code-reviewer** after Step 6 to sanity-check JSON extraction
  logic (fenced block edge cases: multiple fences, no language tag,
  trailing newline inside fence).

## Rollback triggers

- **Model refuses JSON reliably** → keep JSON-first path dormant behind
  `STAGE_STRUCTURED_OUTPUT_ENABLED=0`; ship frontmatter refactor standalone.
- **Frontmatter change breaks existing member tests** → fix the test
  fixtures, do not revert the frontmatter (tests were relying on hardcode).

## Open questions

- Whether to also move delegation-plan execution unit strings into roster.
  Decision: no — delegation vocabulary is stable and lives in its own
  schema already.

## Standalone-context notes

Plan executable from a fresh session using only this document plus repo state.
