# Plan 4 — Web Search Integration (Cluster D)

**Status:** proposed
**Date:** 2026-04-20
**Owner:** TBD
**Related review:** commit 8906ae9 post-review, item P1.7 (web search integration gap)
**Dependencies:** **Plan 3** (shares Stage 1 prompt surface and member frontmatter loader)
**Parallelizable with:** Plans 1, 2, 5 (after Plan 3 lands)
**Estimated scope:** small-medium (~4 files, ~180 LOC)

## Goal

Make the web search capability useful to the council. Today it lives in
`server/execution/web_search.py` and is reachable only through the
`POST /web-search` HTTP endpoint; no board member ever calls it during
deliberation. A Customer Researcher or Market Strategist that cannot retrieve
external evidence is cosmetic.

Additionally:
- Rate limit today is a **module-level** deque shared across all callers.
- There is **no caching**, so identical queries re-hit Tavily on every run.

## Scope

### In scope
- **#7a** Pre-Stage-1 evidence retrieval for members whose frontmatter declares
  `evidence_required: true`.
- **#7b** Per-session rate limit bucket in place of the global deque.
- **#7c** In-memory LRU/TTL cache keyed on normalized query + provider +
  max_results.
- Warnings surfaced onto the session when web search is unavailable or rate-limited.

### Out of scope
- New provider beyond `disabled`/`fake`/`tavily`.
- Vector store, embedding search, long-term retrieval memory.
- Redis, cross-process coordination.
- Any change to Stage 2 or Stage 3 prompts.
- Any automatic approval of untrusted sources (evidence_packet already has a
  warnings field; we simply pass results through).

## Files touched
- `server/members/researcher.md`, `server/members/strategist.md` — set
  `evidence_required: true` in frontmatter
- `server/board/config.py` — extend `BoardMember` dataclass with
  `evidence_required: bool` (reusing Plan 3's loader extension point)
- `server/board/deliberation/orchestrator.py` — pre-Stage-1 evidence hook
- `server/execution/web_search.py` — add cache + per-session rate limit hook
- `server/api/routes/execution.py` — switch `/web-search` endpoint to the
  new per-session limiter
- (new) `server/execution/search_cache.py` — thin TTL/LRU
- `tests/test_web_search_contract.py` — extend
- (new) `tests/test_evidence_injection_contract.py`

## Phase 0 — Reproduce before code

1. **Members never trigger web_search:**
   ```bash
   grep -R "web_search" server/board/ | grep -v 'compat\|shim\|__pycache__'
   ```
   Expected: no matches. Confirms the gap.

2. **No citations in researcher Stage 1:**
   ```python
   def test_researcher_has_no_retrieved_evidence_today(fake_provider):
       session = run_deliberation("How big is the X market?", members=["researcher"])
       stage1 = session.stage1[0].content
       assert "## Retrieved Evidence" not in stage1
   ```
   Passes today (gap confirmation); will become inverted assertion after fix.

3. **Global rate limit leaks across sessions:**
   ```python
   def test_web_search_rate_limit_leaks_across_sessions(tmp_env):
       # fire N requests under session A until 429
       # then session B request → also 429
   ```
   Fails post-fix; passes today.

4. **Cache miss always:**
   ```python
   def test_web_search_repeat_query_hits_provider_twice_today(monkeyprovider):
       await web_search("foo"); await web_search("foo")
       assert monkeyprovider.call_count == 2
   ```
   Passes today; will invert to `== 1` after cache.

## Implementation steps

### Step 1 — Member frontmatter flag
- Extend member dataclass with `evidence_required: bool = False`.
- `loader.py` parses the flag.
- Set `evidence_required: true` on `researcher.md` and `strategist.md`.
  Others stay false.

### Step 2 — Search cache
- `execution/search_cache.py`:
  ```python
  class SearchCache:
      def __init__(self, maxsize=128, ttl_seconds=1800): ...
      def get(self, key: tuple) -> dict | None
      def put(self, key: tuple, value: dict) -> None
  ```
  Implementation: `collections.OrderedDict` + timestamp per entry; evict
  oldest when over maxsize; treat stale entries as miss.
- Normalize query: strip + lowercase + collapse whitespace.
- Key: `(normalized_query, provider, max_results)`.
- Cache only successful non-empty results.

### Step 3 — Per-session rate limit
- Replace module deque with
  `_WEB_SEARCH_REQUESTS: dict[str, deque[float]]` keyed by session id; fall
  back to `"anon"` when caller omits session id.
- `web_search(..., session_id: str | None = None)` threaded through from:
  - The orchestrator hook (passes real session id).
  - `/web-search` endpoint (uses client host as pseudo-session).
- Env tunables unchanged (`AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT`, window).

### Step 4 — Orchestrator pre-Stage-1 hook
- Before `self.stage1(...)`, for each member with `evidence_required=True`:
  - Call `web_search(effective_query, session_id=session_id)`.
  - If results present, attach `## Retrieved Evidence\n<formatted>` as a
    per-member system-prompt addendum passed into `_query_member`.
  - Store the evidence packet id on the session under
    `session.evidence_packets: dict[member_id, packet_id]` so the UI can
    show sources.
- On failure or disabled provider: append warning to
  `session.structured_output_warnings` (reuse existing channel) and proceed
  without evidence — do not fail the deliberation.

### Step 5 — Prompt wiring
- `format_stage1` signature already accepts member-specific addendum via the
  system prompt parameter in `_query_member`. Thread addendum through.
- Keep the addendum short: title + bulleted claim→source lines, ≤500 tokens.

## Test strategy

- **Unit:**
  - `test_search_cache_evicts_expired` and `test_search_cache_lru_order`.
  - `test_rate_limit_per_session_isolated`.
- **Contract:**
  - `test_evidence_injection_contract.py::test_researcher_sees_retrieved_evidence`
    with `WEB_SEARCH_PROVIDER=fake` confirms presence of the addendum and
    that `session.evidence_packets["researcher"]` is set.
- **Integration:**
  - Run deliberation with `evidence_required` false for all members → no
    web search call (current behavior preserved).
- **Smoke (manual):**
  - `WEB_SEARCH_PROVIDER=fake uv run python -m server.cli --members researcher "How big is the foo market?"`
    — Stage 1 contains retrieved-evidence section.
- **Edge:**
  - Provider offline (`disabled`) → no crash, warning recorded.
  - Session hits its rate limit mid-deliberation → warning on subsequent
    members, no deliberation abort.
  - Cache hit returns the same evidence packet id (do not re-persist).

## Cross-cutting execution policy

Same as earlier plans. Highlights:
1. Phase 0 failing tests committed first.
2. Evidence addition must not change deliberation semantics when
   `evidence_required=false` for all members (identical output).
3. LRU/TTL is tiny and stdlib-based. No new dep.
4. If a change breaks the existing `test_web_search_contract.py`, stop and
   check whether behavior changed for the endpoint-only path. Do not modify
   endpoint contract.

## Sub-agent assignments

- **general-purpose** — implementer.
- **superpowers:code-reviewer** — review cache key normalization and rate
  limit key selection.

## Rollback triggers

- **Evidence addendum balloons token usage** (≥15% Stage 1 token growth
  across the next 20 sessions tracked via ledger) → drop max_results to 3
  and/or strip snippet length.
- **Cache returns stale evidence mid-session where query text actually
  changed** → verify normalization, add test; do not remove cache.
- **Rate limit confuses Hermes integration** — Hermes calls CLI one session
  at a time, so per-session buckets reset per run; if manual multi-agent
  parallelism is added later, revisit.

## Open questions

- Whether the strategist should gate on `evidence_required` or on a
  richer capability flag. Decision for V1: boolean flag is enough.
- Source-quality scoring of Tavily results — out of scope; noted as future work.

## Standalone-context notes

Plan executable from a fresh session. Prerequisite: Plan 3 merged
(member frontmatter loader is shared).
