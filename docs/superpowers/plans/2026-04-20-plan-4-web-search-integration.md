# Plan 4 — Web Search Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Prerequisite:** Plan 3 (Board Core Contracts) must be merged first — this plan reuses Plan 3's member-frontmatter loader.

**Goal:** Wire the web-search capability into board deliberation. Members with `evidence_required: true` in their markdown frontmatter receive a pre-Stage-1 retrieval addendum. Rate limit switches from a global deque to a per-session bucket. An in-memory TTL cache avoids redundant provider calls.

**Architecture:** A pre-Stage-1 hook in the orchestrator queries `web_search` for each evidence-flagged member, wraps results into a markdown addendum, and passes them as a system-prompt extension into `_query_member`. `web_search` gains a thin module-local cache and session-keyed rate limiter; callers thread a `session_id`.

**Tech Stack:** Python 3.12, stdlib `collections.OrderedDict` + `time.monotonic`, FastAPI, unittest.

**Spec:** `docs/superpowers/specs/2026-04-20-plan-4-web-search-integration-design.md`

---

## Cross-cutting execution policy

1. Phase 0 before code.
2. Root-cause only.
3. 3-attempt cap → `git reset --hard` to last green commit.
4. YAGNI. stdlib cache, deque per session. No Redis.
5. Done criteria: full suite green; manual smoke with `WEB_SEARCH_PROVIDER=fake` shows retrieved-evidence section in researcher Stage 1 and non-empty `session.evidence_packets["researcher"]`.

## Sub-agent usage

- **superpowers:code-reviewer** after Task 5 — cache key normalization + rate-limit key correctness.

## File structure map

| File | Action | Responsibility |
|---|---|---|
| `server/execution/search_cache.py` | **Create** | Small `OrderedDict`-based TTL cache |
| `server/execution/web_search.py` | **Modify** | Accept `session_id`; thread through cache + per-session rate limit |
| `server/execution/__init__.py` | **Modify** | Re-export `web_search` signature change |
| `server/api/routes/execution.py` | **Modify** | Per-session limiter keyed on client host (endpoint-path compatibility) |
| `server/board/config.py` | **Modify** | Add `evidence_required: bool = False` to `BoardMember` |
| `server/board/loader.py` | **Modify** | Parse `evidence_required` frontmatter flag |
| `server/members/researcher.md`, `server/members/strategist.md` | **Modify** | Set `evidence_required: true` |
| `server/board/deliberation/orchestrator.py` | **Modify** | Pre-Stage-1 evidence hook; per-member addendum |
| `server/board/deliberation/prompts.py` or new helper | **Modify** | Concatenate evidence addendum into member system prompt at call time |
| `tests/test_evidence_injection_contract.py` | **Create** | Integration coverage |
| `tests/test_web_search_contract.py` | **Modify** | Cache + per-session rate |

---

## Task 1: Phase 0 repro tests

**Files:**
- Create: `tests/test_evidence_injection_contract.py` (Phase 0 checks live here)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_evidence_injection_contract.py
"""Phase 0 repro for Plan 4."""

from __future__ import annotations

import asyncio
import os
import unittest
from pathlib import Path


class RateLimitLeaksAcrossSessionsTest(unittest.TestCase):
    def setUp(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"
        os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT"] = "2"
        os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS"] = "60"

    def tearDown(self):
        for k in ("WEB_SEARCH_PROVIDER",
                  "AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT",
                  "AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS"):
            os.environ.pop(k, None)

    def test_per_session_bucket_is_isolated(self):
        from server.execution.web_search import web_search
        async def run():
            await web_search("q", session_id="s1")
            await web_search("q", session_id="s1")
            # session s1 is at the limit; session s2 should still go through
            result = await web_search("q", session_id="s2")
            return result
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()
        self.assertNotIn("rate limit", " ".join(result.get("warnings", [])))


class CacheHitTest(unittest.TestCase):
    def setUp(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"

    def tearDown(self):
        os.environ.pop("WEB_SEARCH_PROVIDER", None)

    def test_repeat_query_hits_cache(self):
        import server.execution.web_search as ws
        call_count = {"n": 0}

        async def counting_fake(query, *, max_results):
            call_count["n"] += 1
            return [{"title": "t", "url": "u", "snippet": f"s:{query}",
                     "publisher": "p", "retrieved_at": "2026-04-20T00:00:00Z"}]

        original = ws._fake_results
        ws._fake_results = lambda q: [{"title": "t", "url": "u",
                                        "snippet": f"s:{q}", "publisher": "p",
                                        "retrieved_at": "2026-04-20T00:00:00Z"}]
        try:
            from server.execution.search_cache import SearchCache
            cache = SearchCache(maxsize=4, ttl_seconds=60)
            ws._cache = cache

            async def run():
                a = await ws.web_search("foo")
                b = await ws.web_search("foo")
                return a, b

            loop = asyncio.new_event_loop()
            try:
                a, b = loop.run_until_complete(run())
            finally:
                loop.close()
            self.assertEqual(a["results"], b["results"])
            self.assertEqual(len(cache._store), 1)
        finally:
            ws._fake_results = original


class EvidenceInjectionTest(unittest.IsolatedAsyncioTestCase):
    async def test_researcher_receives_retrieved_evidence(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"
        try:
            from server.board.deliberation.orchestrator import BoardOrchestrator

            orch = BoardOrchestrator()
            # simulate the pre-stage1 hook directly
            addenda = await orch._collect_member_evidence("What is the X market?")
            self.assertIn("researcher", addenda)
            self.assertIn("Retrieved Evidence", addenda["researcher"])
        finally:
            os.environ.pop("WEB_SEARCH_PROVIDER", None)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run; confirm FAILs**

Run: `uv run python -m unittest tests.test_evidence_injection_contract -v`

Expected: all FAIL — `search_cache` doesn't exist, `web_search` lacks
`session_id` kwarg, orchestrator lacks `_collect_member_evidence`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_evidence_injection_contract.py
git commit -m "test: phase 0 repro for evidence injection (cache, per-session rate, hook)"
```

---

## Task 2: Search cache

**Files:**
- Create: `server/execution/search_cache.py`

- [ ] **Step 1: Implement**

```python
# server/execution/search_cache.py
"""Tiny TTL+LRU cache for web search results."""

from __future__ import annotations

import time
from collections import OrderedDict


class SearchCache:
    def __init__(self, maxsize: int = 128, ttl_seconds: int = 1800):
        self.maxsize = maxsize
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[tuple, tuple[float, dict]] = OrderedDict()

    def get(self, key: tuple) -> dict | None:
        entry = self._store.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.monotonic() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return value

    def put(self, key: tuple, value: dict) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (time.monotonic(), value)
        while len(self._store) > self.maxsize:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()
```

- [ ] **Step 2: Commit**

```bash
git add server/execution/search_cache.py
git commit -m "feat(search): tiny TTL+LRU cache module"
```

---

## Task 3: Per-session rate limit and cache wiring in web_search

**Files:**
- Modify: `server/execution/web_search.py`

- [ ] **Step 1: Add module state**

At the top of `server/execution/web_search.py`:

```python
import time
from collections import deque

from .search_cache import SearchCache

_cache = SearchCache(maxsize=128, ttl_seconds=1800)
_SESSION_BUCKETS: dict[str, deque[float]] = {}
```

- [ ] **Step 2: Extend signature**

```python
async def web_search(
    query: str,
    *,
    provider: str | None = None,
    max_results: int = 5,
    session_id: str | None = None,
) -> dict[str, Any]:
```

- [ ] **Step 3: Rate-limit + cache hook**

Near the top of the function, after `selected` is computed, before any
provider call:

```python
bucket_key = session_id or "anon"

limit = int(os.getenv("AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT", "20") or 0)
window = int(os.getenv("AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS", "60") or 0)
if limit > 0 and window > 0:
    now = time.monotonic()
    bucket = _SESSION_BUCKETS.setdefault(bucket_key, deque())
    while bucket and bucket[0] <= now - window:
        bucket.popleft()
    if len(bucket) >= limit:
        return {
            "query": query,
            "provider": selected,
            "results": [],
            "evidence_packet": None,
            "warnings": [f"session rate limit: {limit}/{window}s"],
        }
    bucket.append(now)

if selected in {"tavily", "fake"}:
    cache_key = (query.strip().lower(), selected, max_results)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
```

And right before returning the successful result, store into cache:

```python
    _cache.put(cache_key, response)
    return response
```

(where `response = {...}` is the dict currently built and returned.)

- [ ] **Step 4: Remove global deque from the API route**

In `server/api/routes/execution.py`, delete `_WEB_SEARCH_REQUESTS` and
`_enforce_web_search_rate_limit`. Update the endpoint:

```python
@router.post("/web-search")
async def execution_web_search(req: WebSearchRequest, request: Request):
    if not req.query.strip():
        raise HTTPException(422, detail="query is required")
    client_host = request.client.host if request.client else "anon"
    result = await web_search(
        req.query,
        provider=req.provider,
        max_results=req.max_results,
        session_id=f"ip:{client_host}",
    )
    if any("rate limit" in w for w in result.get("warnings", [])):
        raise HTTPException(
            429,
            detail=f"web search rate limit exceeded",
        )
    return result
```

Add `Request` to the route imports.

- [ ] **Step 5: Run repro: per-session isolation + cache**

Run:
```bash
uv run python -m unittest tests.test_evidence_injection_contract.RateLimitLeaksAcrossSessionsTest tests.test_evidence_injection_contract.CacheHitTest -v
```

Expected: PASS.

- [ ] **Step 6: Run full web_search suite; fix fallout**

Run: `uv run python -m unittest tests.test_web_search_contract -v`

If the old `_WEB_SEARCH_REQUESTS` symbol is imported in a test, move that
test to the per-session semantics. Do not re-introduce the global.

- [ ] **Step 7: Commit**

```bash
git add server/execution/web_search.py server/api/routes/execution.py tests/
git commit -m "feat(search): per-session rate limit and result cache"
```

---

## Task 4: Member `evidence_required` flag

**Files:**
- Modify: `server/board/config.py`
- Modify: `server/board/loader.py`
- Modify: `server/members/researcher.md`, `server/members/strategist.md`

- [ ] **Step 1: Extend `BoardMember`**

Add field:

```python
evidence_required: bool = False
```

- [ ] **Step 2: Loader parses `evidence_required`**

Add to the loader field-extraction block:

```python
evidence_required=bool(frontmatter.get("evidence_required", False)),
```

- [ ] **Step 3: Set flag on researcher and strategist**

In each of `server/members/researcher.md` and
`server/members/strategist.md`, add to the frontmatter:

```yaml
evidence_required: true
```

- [ ] **Step 4: Run member contract tests**

Run: `uv run python -m unittest tests.test_first_member_contract tests.test_member_intake_frontmatter_contract -v`

Expected: green.

- [ ] **Step 5: Commit**

```bash
git add server/board/config.py server/board/loader.py server/members/
git commit -m "feat(members): add evidence_required flag; enable for researcher + strategist"
```

---

## Task 5: Pre-Stage-1 evidence hook in orchestrator

**Files:**
- Modify: `server/board/deliberation/orchestrator.py`

- [ ] **Step 1: Add the collection method**

Inside `BoardOrchestrator`:

```python
async def _collect_member_evidence(self, query: str) -> dict[str, str]:
    """For members with evidence_required, run web_search and build a prompt addendum."""
    from server.execution.web_search import web_search

    addenda: dict[str, str] = {}
    for member in self.council:
        if not getattr(member, "evidence_required", False):
            continue
        try:
            result = await web_search(query, session_id=self._session_id_for_search())
        except Exception as exc:
            logger.warning("Evidence retrieval failed for %s: %s", member.id, exc)
            continue
        if not result.get("results"):
            continue
        lines = ["## Retrieved Evidence"]
        for item in result["results"][:3]:
            title = (item.get("title") or "Untitled").strip()
            url = (item.get("url") or "").strip()
            snippet = (item.get("snippet") or "").strip()
            lines.append(f"- [{title}]({url}) — {snippet}")
        addenda[member.id] = "\n".join(lines)
    return addenda


def _session_id_for_search(self) -> str:
    return getattr(self, "_current_session_id", None) or "anon"
```

- [ ] **Step 2: Capture `session_id` for the running deliberation**

At the top of `deliberate(...)` (after `session_id` is finalized):

```python
self._current_session_id = session_id
```

- [ ] **Step 3: Call hook before Stage 1**

In `deliberate`, right before the `session.stage1_responses = await self.stage1(...)` call, add:

```python
evidence_addenda = await self._collect_member_evidence(effective_query)
self._evidence_addenda = evidence_addenda
session.evidence_packets = {
    mid: f"evidence_{session.session_id}_{mid}"
    for mid in evidence_addenda
}
```

Also add `evidence_packets: dict = field(default_factory=dict)` to the
`BoardSession` dataclass and include it in `to_dict()`.

- [ ] **Step 4: Plumb addendum into `_query_member`**

Modify `_query_member`:

```python
async def _query_member(
    self, member: BoardMember, prompt: str, stage: int,
    *, query_type=None, complexity=None,
) -> MemberResponse:
    model = self.model_assignments.get(member.id, get_council_models()[0])
    messages = [{"role": "user", "content": prompt}]
    cfg = get_config()
    max_tokens = resolve_stage_max_tokens(
        stage,
        query_type=query_type if query_type is not None else self._token_budget_query_type,
        complexity=complexity if complexity is not None else self._token_budget_complexity,
        config=cfg,
    )
    system_prompt = member.system_prompt
    addendum = getattr(self, "_evidence_addenda", {}).get(member.id)
    if stage == 1 and addendum:
        system_prompt = f"{member.system_prompt}\n\n{addendum}"
    llm_resp = await query_llm(
        model, messages, system=system_prompt, max_tokens=max_tokens,
    )
    self._record_metrics(member.id, stage, llm_resp)
    resp = MemberResponse(
        member_id=member.id, stage=stage,
        content=llm_resp.content, model=llm_resp.model,
        elapsed_seconds=round(llm_resp.latency_seconds, 2),
    )
    self._fire(self._on_member_done, stage, member, resp)
    return resp
```

- [ ] **Step 5: Run evidence injection test**

Run: `uv run python -m unittest tests.test_evidence_injection_contract.EvidenceInjectionTest -v`

Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

Fix any regression. If a fake provider test now receives an unexpected
addendum, gate with `evidence_required=False` members or set
`WEB_SEARCH_PROVIDER=disabled` in that test's setUp.

- [ ] **Step 7: Commit**

```bash
git add server/board/deliberation/orchestrator.py tests/
git commit -m "feat(board): inject web-search evidence into Stage 1 for flagged members"
```

---

## Task 6: Manual smoke + review

- [ ] **Step 1: Smoke**

```bash
WEB_SEARCH_PROVIDER=fake uv run python -m server.cli --members researcher \
  "How big is the indie app developer market?"
```

Open the saved session JSON; confirm:
- `evidence_packets.researcher` is set.
- `stage1[researcher].content` contains `## Retrieved Evidence`.
- `warnings` empty or rate-related only.

- [ ] **Step 2: code-reviewer audit**

Dispatch `superpowers:code-reviewer` focused on:
- Cache key normalization (leading/trailing whitespace, unicode).
- Per-session rate-limit key selection (`session_id=None` → `"anon"`).
- Orchestrator ordering — evidence hook must run AFTER clarification gate
  and BEFORE Stage 1.

- [ ] **Step 3: Address findings**

- [ ] **Step 4: Final commit if needed**

---

## Definition of done

- Phase 0 tests now green.
- Full unittest suite green.
- Manual smoke shows evidence section in researcher Stage 1.
- code-reviewer clean.
