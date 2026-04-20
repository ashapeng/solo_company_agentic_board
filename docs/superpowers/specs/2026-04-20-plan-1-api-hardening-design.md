# Plan 1 — API Hardening (Cluster A)

**Status:** proposed
**Date:** 2026-04-20
**Owner:** TBD
**Related review:** commit 8906ae9 post-review
**Dependencies:** none
**Parallelizable with:** Plans 2, 3, 5
**Estimated scope:** small (~3 files, ~80 LOC net)

## Goal

Close three P0 security gaps in the FastAPI surface without touching deliberation
logic: path traversal on `session_id`, missing rate limit on `/deliberate*`, and a
CORS configuration that accepts arbitrary methods/headers.

## Scope

### In scope
- **#1** Path-traversal validation for `session_id` path parameter
  on `GET /sessions/{session_id}`, `/sessions/{session_id}/adapter`,
  `/sessions/{session_id}/delegation-plan`, `POST /sessions/{session_id}/feedback`.
- **#2** Per-IP rate limit on `POST /deliberate` and `POST /deliberate/stream`.
- **#11** CORS method/header allow-list tightening.

### Out of scope
- Auth flow changes (local-only bypass stays).
- IPv6 normalization rework (tracked separately; reviewer's `::1` claim was already correct).
- Any change to deliberation pipeline, harness, or member logic.

## Files touched
- `server/api/app.py` — CORS config
- `server/api/routes/board.py` — session_id validator, rate-limit hook on two routes
- `tests/test_api_cli_contract.py` — new cases
- (new) `tests/test_api_hardening_contract.py` — dedicated hardening tests

## Phase 0 — Reproduce before code

These tests must be written first and must FAIL against current `main`. Only
proceed to impl once all three confirm the diagnosis.

1. **Path traversal smoke (e2e):**
   ```bash
   uv run uvicorn server.api:app --port 8765 &
   curl -s -o /dev/null -w "%{http_code}\n" \
     "http://127.0.0.1:8765/sessions/..%2F..%2Fetc%2Fpasswd"
   ```
   Expected with current code: anything other than 400.
   Target after fix: 400 with structured error code `invalid_session_id`.

2. **Rate limit smoke (e2e):**
   ```bash
   for i in $(seq 1 10); do
     curl -s -o /dev/null -w "%{http_code}\n" \
       -X POST http://127.0.0.1:8765/deliberate \
       -H "content-type: application/json" \
       -d '{"query":"ping"}'
   done
   ```
   Expected with current code: all 200/5xx, none 429.
   Target after fix: after the 5th request inside 60s → 429 with `Retry-After`.

3. **CORS edge:**
   ```bash
   curl -i -X OPTIONS http://127.0.0.1:8765/deliberate \
     -H "Origin: http://127.0.0.1:8000" \
     -H "Access-Control-Request-Method: TRACE" \
     -H "Access-Control-Request-Headers: X-Evil"
   ```
   Expected with current code: 200 with wildcard Allow-Methods/Headers.
   Target after fix: 400 or missing Allow-Method for TRACE; `X-Evil` not echoed.

## Implementation steps

1. **`session_id` validator.** Add `SESSION_ID_PATTERN = re.compile(r"^board_\d+$")`
   at module top of `routes/board.py`. Add `_validate_session_id(sid)` helper that
   raises `HTTPException(400, detail={"code": "invalid_session_id"})`. Call from
   all 4 routes before any `Path(...)` construction.
   - No change to path parameter typing — FastAPI still accepts the string; we
     constrain inside handler for uniform error.

2. **Per-IP rate limit.**
   - Add module-level `_DELIBERATE_REQUESTS: dict[str, deque[float]]` in
     `routes/board.py` (keyed by client host; deque of monotonic timestamps).
   - Helper `_enforce_deliberate_rate_limit(request)` mirrors
     `routes/execution.py:_enforce_web_search_rate_limit` but per-IP.
   - Env tunables: `AGENTIC_BOARD_DELIBERATE_RATE_LIMIT` (default 5),
     `AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS` (default 60).
   - Pass `request: Request` into both handlers (FastAPI dependency injection).
   - `HTTPException(429, detail={"code": "rate_limited", "retry_after": <int>}, headers={"Retry-After": str(<int>)})`.

3. **CORS tighten.**
   - `allow_methods=["GET", "POST", "PUT", "OPTIONS"]`
   - `allow_headers=["content-type", "authorization"]`
   - Keep `allow_origins` as-is (already pinned to localhost:8000 pair).
   - Leave `allow_credentials` unchanged.

## Test strategy

- **Unit / contract (pytest):**
  - `test_api_hardening_contract.py::test_session_id_rejects_traversal`
    parameterized over `["../etc", "%2e%2e/x", "foo/bar", "board_", ""]`.
  - `test_session_id_accepts_valid_pattern` on `"board_1700000000"`.
  - `test_deliberate_rate_limit_per_ip` uses monkeypatched clock + TestClient
    with two distinct client hosts; confirms isolation.
  - `test_cors_blocks_unexpected_method` via TestClient OPTIONS.
- **Smoke (manual):** three Phase 0 scripts re-run after fix; expected codes invert.
- **Edge:**
  - Rate limit with `client=None` (missing host): fall back to `"anon"` bucket.
  - SSE streaming route (`/deliberate/stream`): rate limit applied BEFORE
    generator starts, so client gets 429 before event stream opens.

## Cross-cutting execution policy

1. **Phase 0 first.** Do not edit code until all three reproduction tests fail
   against current `main`. Commit the failing tests in a single "repro" commit
   to lock the diagnosis.
2. **Root-cause only.** If a test fails for a reason other than the target bug,
   stop and investigate. Do not mask with try/except.
3. **3-attempt cap.** If a single step has three consecutive failing fix
   attempts, run `git reset --hard HEAD~<N>` to the last green commit and
   restart from plan step N−1. Do not stack patches on top of a broken state.
4. **YAGNI.** In-memory deque only. No Redis, no middleware framework, no
   shared rate-limit service.
5. **Done criteria.** All new tests green, all existing tests green,
   `pytest -W error tests/` clean, three Phase 0 smoke scripts now return
   expected fixed codes.

## Sub-agent assignments

- **general-purpose** — primary implementer, writes code + tests.
- **superpowers:code-reviewer** — invoked after the impl pass to check the
  rate-limit implementation for race conditions and off-by-one window math,
  and to confirm the `session_id` regex does not accept edge inputs like
  `board_00000000000000000000` (should accept — unbounded length is fine).
- **security-review** skill — invoked last on the diff for independent audit
  before merge.

## Rollback triggers

- **Rate limit trips SSE keepalives in normal use** → `git revert` the
  rate-limit commit only (keep path-traversal + CORS fixes). Investigate
  whether keepalive generator is being rejected at per-IP bucket.
- **Frontend CORS failure after tighten** → add exact header/method the UI
  actually uses; do not revert to wildcard.

## Open questions

- None. All design decisions resolved during brainstorming.

## Standalone-context notes

Fresh session executing this plan needs only this doc + repo state. No external
context or prior conversation required.
