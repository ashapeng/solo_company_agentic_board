# Plan 1 — API Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close three P0 API security gaps — path traversal on `session_id`, missing rate limit on `/deliberate*`, CORS wildcard methods/headers — without touching deliberation logic.

**Architecture:** Additive defensive layer in FastAPI routes. A regex validator guards path parameters; an in-memory per-IP deque enforces rate limits on two LLM-expensive endpoints; CORS config is constrained to exact methods/headers.

**Tech Stack:** Python 3.12, FastAPI, Starlette TestClient, unittest, stdlib `collections.deque` + `re`.

**Spec:** `docs/superpowers/specs/2026-04-20-plan-1-api-hardening-design.md`

---

## Cross-cutting execution policy (applies to every task below)

1. **Phase 0 before code.** Task 1 writes reproduction tests that MUST fail on current `main`. Do not start Task 2+ until Task 1's commit is green-fails.
2. **Root-cause only.** On unexpected failure, stop, read the stack, identify cause. Never `try/except Exception: pass`.
3. **3-attempt cap.** If one task has three consecutive failing fix attempts, run `git reset --hard <last-green-sha>` and reconsult plan step N−1.
4. **YAGNI.** In-memory deque only. No Redis. No middleware library.
5. **Done criteria.** All new unittest classes green; `uv run python -m unittest discover -s tests -v` fully green; three Phase 0 scripts flip to expected fixed status codes.

## Sub-agent usage

- Task 1 (repro): implementer directly — small.
- Tasks 2–4 (impl): implementer directly.
- Task 5 (security audit): dispatch **security-review** skill on the diff before merge.
- Optional: **superpowers:code-reviewer** on Task 3 (rate-limit math).

## File structure map

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/test_api_hardening_contract.py` | **Create** | All three repro + fix assertions live here; one TestCase per bug class |
| `server/api/routes/board.py` | **Modify** | Add `SESSION_ID_PATTERN`, `_validate_session_id`, per-IP deque + `_enforce_deliberate_rate_limit`, wire into 4 routes |
| `server/api/app.py` | **Modify** | Narrow `allow_methods` and `allow_headers` |

No new modules. Everything lives where it is consumed.

---

## Task 1: Write failing reproduction tests (Phase 0)

**Files:**
- Create: `tests/test_api_hardening_contract.py`

- [ ] **Step 1: Create the test file with three failing tests**

```python
# tests/test_api_hardening_contract.py
"""Phase 0 reproduction tests for API hardening plan.

These MUST FAIL on current main. They lock the diagnosis for:
  1. Path traversal on /sessions/{session_id}
  2. Missing rate limit on /deliberate
  3. CORS wildcard methods/headers
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from server.api.app import app


class SessionIdPathTraversalTest(unittest.TestCase):
    def setUp(self):
        os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)

    def test_traversal_in_session_id_is_rejected(self):
        resp = self.client.get("/sessions/..%2F..%2Fetc%2Fpasswd")
        self.assertEqual(
            resp.status_code, 400,
            f"expected 400 invalid_session_id, got {resp.status_code}: {resp.text}",
        )
        self.assertEqual(resp.json().get("detail", {}).get("code"), "invalid_session_id")

    def test_adapter_route_also_rejects_traversal(self):
        resp = self.client.get("/sessions/..%2F..%2Fetc%2Fpasswd/adapter")
        self.assertEqual(resp.status_code, 400)

    def test_delegation_plan_route_also_rejects_traversal(self):
        resp = self.client.get("/sessions/..%2F..%2Fetc%2Fpasswd/delegation-plan")
        self.assertEqual(resp.status_code, 400)

    def test_valid_session_id_shape_is_accepted(self):
        # Shape is valid even if session file is absent (→ 404 by design).
        resp = self.client.get("/sessions/board_1700000000")
        self.assertIn(resp.status_code, (200, 404))


class DeliberateRateLimitTest(unittest.TestCase):
    def setUp(self):
        os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"
        os.environ["AGENTIC_BOARD_DELIBERATE_RATE_LIMIT"] = "3"
        os.environ["AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS"] = "60"
        self.client = TestClient(app)

    def tearDown(self):
        for key in (
            "AGENTIC_BOARD_ALLOW_REMOTE",
            "AGENTIC_BOARD_DELIBERATE_RATE_LIMIT",
            "AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS",
        ):
            os.environ.pop(key, None)
        # Purge module-level bucket between tests.
        from server.api.routes import board as board_routes
        board_routes._DELIBERATE_REQUESTS.clear()

    def test_fourth_request_in_window_is_rate_limited(self):
        fake = AsyncMock()
        fake.return_value = type("S", (), {"to_dict": lambda self: {"ok": True}})()
        with patch(
            "server.api.routes.board.BoardOrchestrator.deliberate",
            new=fake,
        ):
            for _ in range(3):
                resp = self.client.post("/deliberate", json={"query": "ping"})
                self.assertEqual(resp.status_code, 200, resp.text)
            resp = self.client.post("/deliberate", json={"query": "ping"})
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json().get("detail", {}).get("code"), "rate_limited")
        self.assertIn("Retry-After", resp.headers)


class CorsTighteningTest(unittest.TestCase):
    def setUp(self):
        os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"
        self.client = TestClient(app)

    def tearDown(self):
        os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)

    def test_unexpected_method_is_not_advertised(self):
        resp = self.client.options(
            "/deliberate",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "TRACE",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        allow_methods = resp.headers.get("access-control-allow-methods", "")
        self.assertNotIn("TRACE", allow_methods)
        self.assertNotEqual(allow_methods.strip(), "*")

    def test_unexpected_header_is_not_echoed(self):
        resp = self.client.options(
            "/deliberate",
            headers={
                "Origin": "http://127.0.0.1:8000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-evil",
            },
        )
        allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
        self.assertNotIn("x-evil", allow_headers)
        self.assertNotEqual(allow_headers.strip(), "*")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm they fail**

Run: `uv run python -m unittest tests.test_api_hardening_contract -v`

Expected: all FAILs. Specifically:
- `test_traversal_in_session_id_is_rejected` → got 404 or 200 (no 400 yet)
- `test_fourth_request_in_window_is_rate_limited` → got 200 (no 429 yet)
- `test_unexpected_method_is_not_advertised` → `allow_methods` contains `*`

If any test passes against current main, **stop** — the diagnosis is wrong. Do not proceed.

- [ ] **Step 3: Commit the failing Phase 0 tests**

```bash
git add tests/test_api_hardening_contract.py
git commit -m "test: add failing repro for api hardening (path traversal, rate limit, cors)"
```

---

## Task 2: Add `session_id` path-parameter validator

**Files:**
- Modify: `server/api/routes/board.py`

- [ ] **Step 1: Add regex + helper near the top of `board.py`**

Insert after the existing `import` block (around line 22):

```python
import re

SESSION_ID_PATTERN = re.compile(r"^board_\d+$")


def _validate_session_id(session_id: str) -> None:
    """Reject any session_id that escapes the sessions directory."""
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            400,
            detail={
                "code": "invalid_session_id",
                "message": "session_id must match ^board_\\d+$",
            },
        )
```

- [ ] **Step 2: Wire validator into 4 session routes**

Add `_validate_session_id(session_id)` as the first line inside each handler:

```python
@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    _validate_session_id(session_id)
    # ...existing body unchanged...

@router.get("/sessions/{session_id}/adapter")
async def get_session_adapter(session_id: str):
    _validate_session_id(session_id)
    # ...existing body unchanged...

@router.get("/sessions/{session_id}/delegation-plan")
async def get_session_delegation_plan(session_id: str):
    _validate_session_id(session_id)
    # ...existing body unchanged...

@router.post("/sessions/{session_id}/feedback")
async def feedback(session_id: str, req: FeedbackRequest):
    _validate_session_id(session_id)
    # ...existing body unchanged...
```

- [ ] **Step 3: Run path-traversal tests; confirm green**

Run: `uv run python -m unittest tests.test_api_hardening_contract.SessionIdPathTraversalTest -v`

Expected: all 4 methods PASS.

- [ ] **Step 4: Run full suite; confirm no regression**

Run: `uv run python -m unittest discover -s tests -v`

Expected: no test that previously passed now fails. (Some tests may send
`session_id="api_contract_test"` etc.; those may need updating. If so,
update those test fixtures to use a valid `board_…` id — do NOT weaken the
regex. Root-cause the bug in the test, not the fix.)

- [ ] **Step 5: Commit**

```bash
git add server/api/routes/board.py tests/
git commit -m "feat(api): validate session_id path parameter against board_<ts> regex"
```

---

## Task 3: Per-IP rate limit on `/deliberate` and `/deliberate/stream`

**Files:**
- Modify: `server/api/routes/board.py`

- [ ] **Step 1: Add module-level bucket and enforcer**

At the top of `server/api/routes/board.py`, near the router declaration, add:

```python
import os
import time
from collections import deque
from fastapi import Request

_DELIBERATE_REQUESTS: dict[str, deque[float]] = {}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(0, value)


def _enforce_deliberate_rate_limit(request: Request) -> None:
    limit = _positive_int_env("AGENTIC_BOARD_DELIBERATE_RATE_LIMIT", 5)
    window = _positive_int_env("AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS", 60)
    if limit <= 0:
        return

    bucket_key = request.client.host if request.client else "anon"
    bucket = _DELIBERATE_REQUESTS.setdefault(bucket_key, deque())
    now = time.monotonic()
    cutoff = now - window
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = max(1, int(bucket[0] + window - now) + 1)
        raise HTTPException(
            429,
            detail={"code": "rate_limited", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
```

- [ ] **Step 2: Thread `request: Request` into both handlers and call enforcer first**

```python
@router.post("/deliberate")
async def deliberate(req: QueryRequest, request: Request):
    _enforce_deliberate_rate_limit(request)
    # ...existing body unchanged...


@router.post("/deliberate/stream")
async def deliberate_stream(req: QueryRequest, request: Request):
    _enforce_deliberate_rate_limit(request)
    # ...existing body unchanged...
```

Enforcer must fire **before** `BoardOrchestrator(...)` is constructed, so
the limit rejects the request before any LLM spend.

- [ ] **Step 3: Run rate-limit test; confirm green**

Run: `uv run python -m unittest tests.test_api_hardening_contract.DeliberateRateLimitTest -v`

Expected: PASS.

- [ ] **Step 4: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

If prior `/deliberate` tests fail because the per-IP bucket is shared,
ensure each test purges `_DELIBERATE_REQUESTS.clear()` in tearDown. Do NOT
remove the enforcer.

- [ ] **Step 5: Commit**

```bash
git add server/api/routes/board.py
git commit -m "feat(api): add per-IP rate limit to /deliberate and /deliberate/stream"
```

---

## Task 4: Tighten CORS

**Files:**
- Modify: `server/api/app.py`

- [ ] **Step 1: Replace wildcard allow_methods/headers**

In `server/api/app.py` find:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Replace with:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["content-type", "authorization"],
)
```

- [ ] **Step 2: Run CORS test; confirm green**

Run: `uv run python -m unittest tests.test_api_hardening_contract.CorsTighteningTest -v`

Expected: PASS.

- [ ] **Step 3: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

If the frontend uses a header beyond `content-type`/`authorization` (check
`ui/src/` for any `fetch(... headers: {...})` calls), add that exact header
name to the allow list. Do not re-introduce `"*"`.

- [ ] **Step 4: Commit**

```bash
git add server/api/app.py
git commit -m "feat(api): restrict CORS methods and headers to explicit allow-list"
```

---

## Task 5: Independent security audit

- [ ] **Step 1: Invoke security-review skill**

Run the `security-review` slash command on the three commits created by
Tasks 2–4. It should examine:
- The regex for bypass characters.
- The rate-limit deque for time-of-check-time-of-use edge cases.
- The CORS allow-list for overlooked headers.

- [ ] **Step 2: Address any findings**

If audit flags issues, file follow-up tasks. Re-run full suite after fixes.

- [ ] **Step 3: Final verification**

Run: `uv run python -m unittest discover -s tests -v`
Run: `uv run python -m unittest tests.test_api_hardening_contract -v`
Manually run the three Phase 0 curl scripts from the spec; confirm:
- Path traversal → 400
- Rate limit fires after N requests → 429
- TRACE method not advertised

- [ ] **Step 4: Final commit if any fixups needed, else done**

---

## Definition of done

- All commits from Tasks 1–4 landed on the branch.
- `uv run python -m unittest discover -s tests -v` fully green.
- `tests/test_api_hardening_contract.py` fully green.
- security-review skill reported clean (or all findings resolved).
- Manual curl smoke from Phase 0 confirms each fix.
