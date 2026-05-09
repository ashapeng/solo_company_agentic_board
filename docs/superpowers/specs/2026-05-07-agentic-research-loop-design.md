# Agentic Research Loop — Design Spec

- **Status**: Draft (Phase 1 ready for implementation planning)
- **Date**: 2026-05-07
- **Owner**: Peng
- **Drives**: 5–7 day demo, longer-term business-decision use of the board
- **Branch**: `feat/agentic-research`

## 1. Context & motivation

Today, every board member is a single-turn LLM call with a rich system prompt.
Members can consume `<Retrieved Evidence>` blocks, but those blocks are
fetched by `_collect_member_evidence()` *before* Stage 1 starts and are
appended to the system prompt as static markdown. Members cannot:

- call any tool during analysis,
- iteratively research a claim,
- read a JS-rendered or anti-bot-protected page,
- pause to ask the user a clarifying question and resume,
- cite sources that survive in a structured form.

The classifier (`server/board/deliberation/classifier.py`) is similarly a
one-shot LLM call with regex parsing — no clarification, no intent
decomposition.

This spec turns each member into a research-capable agent with a tool-use
loop, gives the chairperson an intake turn that can ask the user clarifying
questions, and rewires `live.py` to run this conversational research flow as
its primary script. The 4-stage flow is preserved as a legacy script for
backwards compatibility.

## 2. Goals & non-goals

### Goals (Phase 1, demo slice — 5–7 days)

1. Members can call a small set of tools (`web_search`, `open_browser`,
   `fetch_url`, `ask_user_clarifying_question`) inside a budgeted tool-use
   loop.
2. Chairperson runs an intake turn that disambiguates the query, optionally
   asks the user 1–3 clarifying questions, and emits a structured
   `RoutingDecision`.
3. `live.py` plays a `live_research` script: chair intake → first member
   round (parallel) → secretary brief.
4. Local Chrome is driven via direct Python Playwright with the user's real
   profile (cookies, logged-in sessions). Tavily is the fallback.
5. Two members upgraded for the demo: Strategist and Researcher. Other
   members continue on the legacy single-call path with `mode=fast`.
6. CLI demo runs end-to-end in <10 minutes for a deep query.

### Goals (Phase 2 — week 2–3)

1. All seven active members upgraded.
2. Mid-deliberation follow-up channel: user can type "Strategist, search X"
   while results stream; the runtime re-invokes that member with deep
   budget.
3. Web UI streams tool events.
4. `validate_claim` tool.
5. Role-tuned tool subsets and member-specific `web_search` augmentation.
6. Secretary brief gains a deduplicated `## Sources` section.

### Goals (Phase 3 — week 4)

1. Harness ledger persists tool calls per member per session for replay,
   cost accounting, and tuning.
2. Adaptive depth refinement uses recorded session data.
3. Documented graceful fallbacks for every tool failure mode.

### Non-goals

- MCP servers. We use direct Python Playwright. The tool registry can wrap
  an MCP-served tool later if needed; not required for this scope.
- Cloud browser services (Browserbase / Anchor). Cost-prohibitive for the
  intended single-user use case.
- Multi-tenant browser pools.
- Source quality scoring beyond the existing `[SEARCH_EVIDENCE]` /
  `[DOMAIN_KNOWLEDGE]` / `[UNVERIFIED]` tags members already use.
- Replacing the four-stage flow. It stays as `script="four_stage"`.
- Changes to member identity, role boundaries, or domain expertise. We
  add a Research Protocol section to each prompt; we do not rewrite them.

## 3. Architecture overview

```
                    ┌─────────────────────────────────┐
                    │  USER QUERY                     │
                    └────────────────┬────────────────┘
                                     ▼
                    ┌─────────────────────────────────┐
                    │  CHAIRPERSON INTAKE TURN        │
                    │  (interpret, optionally ask     │
                    │   clarifying questions, emit    │
                    │   RoutingDecision)               │
                    └────────────────┬────────────────┘
                                     ▼
                    ┌─────────────────────────────────┐
                    │  ADAPTIVE ROUTER                │
                    │  (chair-decided + user override)│
                    └────────────────┬────────────────┘
                                     ▼
   ┌─────────────────────────────────┴─────────────────────────────────┐
   ▼                                                                   ▼
┌──────────────────────────┐                           ┌──────────────────────────┐
│  agentic_member_turn     │   parallel in standard;   │  agentic_member_turn     │
│  ┌────────────────────┐  │   sequential in live      │  ┌────────────────────┐  │
│  │ tool-use loop       │  │   continuation           │  │ tool-use loop       │  │
│  │  - web_search       │  │                           │  │  - web_search       │  │
│  │  - open_browser     │  │                           │  │  - open_browser     │  │
│  │  - fetch_url        │  │                           │  │  - fetch_url        │  │
│  │  - ask_user         │  │                           │  │  - ask_user         │  │
│  └────────────────────┘  │                           │  └────────────────────┘  │
└──────────────────────────┘                           └──────────────────────────┘
                                     │
                                     ▼
                    ┌─────────────────────────────────┐
                    │  SECRETARY BRIEF                │
                    │  (cites sources)                │
                    └─────────────────────────────────┘
```

Three new components:

1. **`server/board/tools.py`** — tool registry: `(name, description, parameters_schema, handler)` per tool. Provider-agnostic JSON schema.
2. **Tool seam in `server/board/llm.py`** — `query_llm()` and `query_llm_stream()` accept `tools` and `tool_choice`; `LLMResponse` gains `tool_calls`. Each provider handler builds the provider-specific tools payload and parses tool_calls back.
3. **`agentic_member_turn`** — wrapper around `query_llm()` that runs a tool-use loop with a `ToolBudget`. Lives in `orchestrator.py`, called by both the legacy 4-stage path and the new live runtime.

One new turn type:

4. **Chair intake turn** — `server/board/deliberation/intake.py` + `server/protocols/chair_intake.md`. Same chairperson model, different system prompt, smaller toolset. Emits `RoutingDecision` JSON.

One existing module evolved:

5. **`server/board/deliberation/live.py`** — gains `script` field (`live_research` default, `four_stage` legacy), follow-up queue, tool budgets per member, new event types.

## 4. Components

### 4.1 Tool registry (`server/board/tools.py`)

```python
@dataclass
class Tool:
    name: str
    description: str
    parameters: dict           # JSON schema
    handler: Callable[..., Awaitable[ToolResult]]

@dataclass
class ToolResult:
    content_for_model: str      # what gets fed back as role="tool" content
    summary: str                # short user-facing summary for events
    cost_units: float           # for budget accounting (1.0 = web_search, etc.)
    artifact_id: str | None     # optional pointer to evidence packet
    error: str | None
```

Phase 1 tools:

| Name | Purpose | Cost units | Notes |
|---|---|---|---|
| `web_search` | Search the web. Wraps existing `execution/web_search.py`. Defaults to `WEB_SEARCH_PROVIDER` env (Tavily for demo). | 1.0 | Returns up to 10 results, each with `title`, `snippet`, `url`, `retrieved_at`. |
| `fetch_url` | HTTP GET, returns text. | 0.5 | Fast; fails on JS-rendered or anti-bot pages. |
| `open_browser` | Drive local Chrome via Playwright; returns rendered page text. | 3.0 | See §4.4. |
| `ask_user_clarifying_question` | Pause and ask the user. | 2.0 | Only enabled for chair (default) and members in `deep` mode. |

`validate_claim` ships in Phase 2.

The handler for `web_search` is a thin wrapper around `web_search()` in
`execution/web_search.py` that also writes an evidence packet via
`execution/evidence.py` and returns the packet id as `artifact_id`.

### 4.2 LLM client seam (`server/board/llm.py`)

Additions:

```python
@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    def to_openai(self) -> dict: ...
    def to_dashscope(self) -> dict: ...
    def to_gemini(self) -> dict: ...

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)  # NEW
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    finish_reason: str | None = None
    response_id: str | None = None

async def query_llm(
    model: str,
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict] | None = None,        # NEW
    tool_choice: str = "auto",               # NEW: auto|none|required
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: float = 240.0,
    fallback: bool = True,
) -> LLMResponse: ...
```

Per-provider implementation:

- **DeepSeek, Kimi, Z.AI** (OpenAI-compatible): pass `tools=[...], tool_choice=...` directly. Parse `choices[0].message.tool_calls` into `LLMResponse.tool_calls`. Append `assistant` message with `tool_calls` field, then `tool` role messages with `tool_call_id`. Standard OpenAI shape.
- **Qwen (DashScope native)**: pass `tools` in `parameters`. Parse `output.choices[0].message.tool_calls`. Same OpenAI-shaped tool_call structure under DashScope's response wrapper.
- **Gemini (google-genai)**: convert tool schemas to `genai_types.Tool(function_declarations=[FunctionDeclaration(name=..., description=..., parameters=...)])`. Pass via `config.tools`. Parse `response.candidates[0].content.parts` for `function_call` parts (each has `.name`, `.args`).
- **OpenRouter**: pass through directly (OpenAI shape).

Streaming (`query_llm_stream`): tool_call deltas accumulate into a complete
`ToolCall` per `id`; emit a `ToolCallReadyEvent` on the stream when each
tool_call's arguments parse cleanly. The harness UI groups deltas by id.

Tool message format (multi-provider):

```python
# Assistant turn that calls a tool
{"role": "assistant", "content": "I need to verify market size.",
 "tool_calls": [{"id": "tc_001", "type": "function",
                 "function": {"name": "web_search",
                              "arguments": "{\"query\": \"...\"}"}}]}

# Tool result
{"role": "tool", "tool_call_id": "tc_001",
 "content": "Results: 1. ... 2. ..."}
```

Per-provider adapters convert this canonical shape to/from the provider's
native format.

Phase 1 implements tool calling for **Kimi** (chair) and **DeepSeek**
(council) only. Other providers' handlers raise
`NotImplementedError("tools not yet wired for <provider>")` if `tools` is
non-None; this is reached only if the user overrides `COUNCIL_MODELS` to
include those providers in Phase 1. Phase 2 wires the rest.

### 4.3 Member tool-loop (`agentic_member_turn` in `orchestrator.py`)

```python
@dataclass
class ToolBudget:
    tool_calls_max: int
    wall_seconds_max: int
    per_call_timeout: float
    open_browser_max: int
    web_search_max: int
    ask_user_max: int

    tool_calls_used: int = 0
    wall_seconds_used: float = 0.0
    sub_used: dict[str, int] = field(default_factory=dict)

    def can_call(self, name: str) -> bool: ...
    def spend(self, name: str, cost: float) -> None: ...
    def exhausted(self) -> bool: ...

@dataclass
class MemberTurnResult:
    content: str
    tool_calls_made: int
    evidence_packets: list[str]    # ids
    finish_reason: str | None
    aborted: bool = False
    abort_reason: str | None = None

async def agentic_member_turn(
    member: BoardMember,
    model: str,
    system_prompt: str,
    initial_user_message: str,
    *,
    tools: list[Tool],
    budget: ToolBudget,
    session: BoardSession,
    stage: int,
    on_event: Callable[[Event], None],
) -> MemberTurnResult: ...
```

Loop:

```
1. messages = [user message]
2. while True:
3.   if budget.exhausted(): force_finish_and_return()
4.   response = await query_llm(model, messages, tools=available_tools, ...)
5.   if not response.tool_calls:
6.     return MemberTurnResult(content=response.content, ...)
7.   append assistant message with tool_calls
8.   results = await asyncio.gather(*[execute_tool(tc, ...) for tc in response.tool_calls])
9.   for tc, result in zip(response.tool_calls, results):
10.    append tool message
11.    budget.spend(tc.name, result.cost_units)
12.    on_event(ToolResultEvent(...))
```

Force-finish: when `budget.exhausted()` between iterations, append a system
message instructing the model to write its final analysis with what it has,
mark gaps `[UNRESOLVED]`, then run one final LLM call with
`tool_choice="none"` and return.

`available_tools` is a budget-filtered slice of `tools` — if `open_browser`
sub-budget is spent, it's removed from the list passed to the next LLM
call. This keeps the model from emitting tool_calls we'd reject.

Default budgets:

| Mode | tool_calls | wall_s | per_call_timeout | open_browser | web_search | ask_user (member) | ask_user (chair) |
|------|------------|--------|------------------|--------------|------------|-------------------|------------------|
| fast | 0 | 60 | 240 | 0 | 0 | 0 | 1 |
| standard | 3 | 180 | 240 | 1 | 3 | 0 | 2 |
| deep | 8 | 480 | 240 | 3 | 6 | 1 | 3 |

`per_call_timeout` is the per-LLM-call timeout, applied via `query_llm`'s
existing `timeout` parameter.

### 4.4 Browser tool (`open_browser`)

Direct Python Playwright. Auto-detects Chrome user data directory:

| OS | Default path |
|---|---|
| Linux | `~/.config/google-chrome` (profile: `Default`) |
| macOS | `~/Library/Application Support/Google/Chrome` |
| Windows | `%LOCALAPPDATA%\Google\Chrome\User Data` |

Override via `AGENTIC_BOARD_CHROME_USER_DATA_DIR` env var.

Modes:

- `AGENTIC_BOARD_BROWSER=chrome` (default for local dev): Playwright
  launches Chromium with `user_data_dir=<resolved path>`,
  `channel="chrome"`, headed by default for demo. Set
  `AGENTIC_BOARD_BROWSER_HEADED=0` for headless.
- `AGENTIC_BOARD_BROWSER=tavily`: skip Playwright entirely. `open_browser`
  internally re-routes to Tavily's extract API (or a `web_search` +
  top-result `fetch_url`). For demo machines without Chrome.
- `AGENTIC_BOARD_BROWSER=disabled`: tool returns
  `{error: "browser disabled"}`. Member treats it as a failed tool call
  and proceeds.

Implementation note: Chrome with `user_data_dir` cannot run if Chrome is
already open with that profile. Phase 1 uses the user's profile directory
with the `Default` sub-profile name; collision is detected via Playwright's
launch error and surfaces as a clear runtime message ("Close Chrome and
retry, or set `AGENTIC_BOARD_BROWSER=tavily`"). Phase 2 may copy the
profile to a shadow directory to avoid the collision; out of scope for now.

Page extraction: by default, `wait_for_load_state("networkidle")` then
`page.content()`, then convert HTML→markdown via `markdownify` (new
dependency). `extract=text` strips to plain text; `extract=html` returns
raw. Truncate at 12,000 chars before returning to the model.

Concurrency: Phase 1 enforces a process-wide semaphore of 1 — only one
`open_browser` call at a time. Members in parallel queue on this semaphore.

### 4.5 Chair intake & router (`server/board/deliberation/intake.py`)

```python
@dataclass
class MemberAssignment:
    member_id: str
    mode: str          # fast|standard|deep
    focus: str         # one-line directive for this member
    priority: int

@dataclass
class RoutingDecision:
    interpreted_query: str
    decision_type: str
    complexity: str       # low|medium|high
    importance: str       # routine|notable|critical
    rationale: str

    members: list[MemberAssignment]
    script: str           # "live_research" default | "four_stage"
    deep_research_dossier: bool

async def run_chair_intake(
    raw_query: str,
    *,
    user_overrides: ChairOverrides,
    session: BoardSession,
    on_event: Callable[[Event], None],
) -> RoutingDecision: ...
```

Intake prompt (`server/protocols/chair_intake.md`) instructs the chair to:

1. Read the query.
2. Identify essential ambiguities (segment, stage, geo, constraints, scale).
3. Optionally do up to 1 `web_search` to ground unfamiliar terms.
4. If essential context is missing AND not searchable, call
   `ask_user_clarifying_question` (up to 3, stop early when clear).
5. Emit final structured `RoutingDecision` JSON via a constrained final
   call (`tool_choice="none"`, JSON-schema response format).

The chair's tools at intake: `web_search`, `ask_user_clarifying_question`.
No `open_browser` — keeps intake fast.

Routing heuristics in the prompt:

| Signal | → mode |
|---|---|
| `complexity=low` AND `importance=routine` | `fast` for everyone |
| `decision_type ∈ {strategic, customer}` AND `importance ∈ {notable, critical}` | `deep` for primary domain owner, `standard` for others |
| `decision_type=technical` AND `complexity=high` | `deep` for architect+builder, `standard` for others |
| Default | `standard` |

User overrides (sources):

1. CLI flag `--depth fast|standard|deep` → applies to all members.
2. CLI flag `--members <ids>` → restricts roster.
3. Magic prefix `"deep research:"` in the query → equivalent to
   `--depth deep`.
4. Phrases like `"strategist: search X"` parsed by `parse_followup` →
   member-specific focus and `mode=deep`.

If `RoutingDecision` JSON fails to parse, fall back to
`DEFAULT_ROUTING`: existing classifier output, all matched members in
`standard` mode, `script="live_research"`, no dossier.

### 4.6 Live mode integration (`server/board/deliberation/live.py`)

`LiveSession` gains:

- `script: str` — `"live_research"` (default) or `"four_stage"`.
- `routing: RoutingDecision | None` — populated after intake.
- `pending_followups: asyncio.Queue[Followup]` — for mid-deliberation
  user input (Phase 2; Phase 1 leaves the queue but never reads from it).
- `tool_budgets: dict[str, ToolBudget]` — per-member budgets, derived
  from `routing.members[*].mode` and the budget table in §4.3.

`script="live_research"` flow (Phase 1):

```
1. Chair intake turn → RoutingDecision
2. (Phase 2) Optional shared dossier turn if routing.deep_research_dossier
3. First member round: parallel agentic_member_turn for each assigned member
4. Live continuation: existing TRIGGER_RULES select next speaker; each turn
   is also agentic
5. Quiet point reached → secretary brief turn
6. (Phase 2) Idle, watch pending_followups queue
```

Phase 1 stops live continuation after the first round (step 3) for the demo
— behaviour matches a richer version of the four-stage flow. Phase 2
re-enables steps 4 and 6.

**Phase 1 mode override**: only `strategist` and `researcher` have Research
Protocol prompts in Phase 1. The live runtime forces any other member's
mode to `fast` regardless of the chair's routing decision (`mode=fast`
means `tools=None` is passed to `query_llm()`, so behaviour is identical
to today's single-call path). This avoids giving tools to members whose
prompts don't yet instruct them in tool use. The override lifts in
Phase 2 once all members get the Research Protocol section.

`script="four_stage"` (legacy):

- Existing `_run_four_stage()` orchestrator runs unchanged, except
  `_query_member()` is replaced by a thin wrapper that calls
  `agentic_member_turn` with the member's mode-derived budget. With
  `mode=fast`, budgets allow zero tool calls and behaviour is identical
  to today. Stage 0 prepends a chair intake (skippable via
  `--intake skip`).

### 4.7 Member prompt updates

Each `server/members/*.md` gets a new section appended:

```markdown
## Research Protocol

You have tools to gather evidence:
- `web_search(query)` — facts, market data, current events.
- `open_browser(url)` — full page content; use after a search returns
  a promising URL OR for sites that block simple fetches.
- `fetch_url(url)` — plain HTML/JSON; faster than open_browser.
- `ask_user_clarifying_question(question, why_it_matters)` — ONLY when
  the answer materially changes your analysis AND cannot be found by
  search. (Available only in deep mode.)

Rules:
1. Use tools BEFORE making a load-bearing factual claim. If your numbers
   depend on a market figure, search for it.
2. Prefer one focused query over many vague ones.
3. Do NOT use ask_user for things you can search for.
4. After collecting evidence, write your analysis. Cite sources inline
   as [source: <title>, <url>, retrieved <date>].
5. If a load-bearing claim remains [UNVERIFIED] after using your search
   budget, say so explicitly and explain why it matters.

Your tool budget for this turn: {{BUDGET_DESCRIPTION}}.
```

`{{BUDGET_DESCRIPTION}}` is rendered at runtime: e.g.,
`"3 tool calls, 1 browser open, 3 web searches, 180s wall budget"`.

Phase 1 updates Strategist and Researcher only. Phase 2 updates the rest
and adds role-tuned tool subsets.

### 4.8 Secretary brief

Phase 1: no structural change to the secretary brief. Members already
emit `[SEARCH_EVIDENCE]` tags and inline citations from their Research
Protocol prompts; the secretary preserves them.

Phase 2: `server/protocols/stage4_secretary_brief.md` and `secretary.md`
gain a `## Sources` section instruction:

```markdown
## Sources
1. <Title> — <URL> (retrieved YYYY-MM-DD; used by: Strategist, Researcher)
```

Phase 1 stretch goal if time permits on day 7.

## 5. Data flow

### Phase 1 demo flow (CLI)

```
$ uv run python -m server.cli "Should I build an AI tool for marketing agencies?" \
      --depth deep --members strategist,researcher --live

[chair intake]
> CHAIR: I want to clarify before we research. Are you targeting independent
  agencies or in-house teams? (1/3)
< user: Independent digital agencies, 10–50 people.
> CHAIR: One more — geographic focus? US/EU/global?
< user: US first, EU later.
> CHAIR: Understood. Routing to Strategist (deep) and Researcher (deep).

[strategist]
  ↳ web_search("agency campaign brief automation market 2026")  [1.2s]
  ↳ web_search("US digital agency tooling spend independent 10-50")  [0.9s]
  ↳ open_browser("https://state-of-agency-tools-2025.com")  [12s, Chrome opens]
  Strategist analysis: TAM/SAM/SOM, segmentation, beachhead. With
  inline citations.

[researcher]
  ↳ web_search("account director campaign brief workflow pain")
  ↳ ask_user: "Have you done any customer interviews already? (it changes
     whether I prioritize design of new ones vs synthesis of existing ones)"
  < user: No interviews yet.
  ↳ web_search("agency account director time study")
  Researcher analysis: JTBD, persona hypotheses, signal assessment. With
  citations.

[secretary]
  Brief with Agreements / Conflicts / Open Questions.
```

### Sequence: a single `agentic_member_turn`

```
agentic_member_turn(member=strategist, mode=deep)
│
├── on_event(MemberStartEvent)
├── messages = [user query + role-specific addendum]
├── loop iteration 1:
│   ├── on_event(MemberThinkingEvent)
│   ├── query_llm(model=deepseek-v4-pro, tools=[web_search, ...], tool_choice=auto)
│   │   → response.tool_calls = [ToolCall(web_search, {"query": "..."})]
│   ├── append assistant message with tool_calls
│   ├── on_event(ToolCallEvent)
│   ├── execute_tool → ToolResult(content_for_model="...", artifact_id="ep_017")
│   ├── append tool message
│   ├── on_event(ToolResultEvent)
│   └── budget.spend("web_search", 1.0)
├── loop iteration 2:
│   ├── query_llm → tool_calls = [open_browser, ...]
│   ├── ... (semaphore acquires; Chrome opens)
├── loop iteration 3:
│   ├── query_llm → no tool_calls, content="Strategist analysis: ..."
│   └── return MemberTurnResult(content=..., tool_calls_made=3, ...)
└── on_event(MemberCompleteEvent)
```

## 6. Phasing

### Phase 1 — demo slice (5–7 days)

| Day | Deliverable | Verification |
|---|---|---|
| 1 | Tool calling in `llm.py` for Kimi + DeepSeek. `tools=` parameter, `LLMResponse.tool_calls`, `role="tool"` message support. | `scripts/smoke_tool_call.py` issues a fake-schema search request to each, returns parsed `ToolCall`. |
| 2 | `server/board/tools.py` registry with `web_search`, `fetch_url`, `ask_user_clarifying_question`. | `scripts/smoke_tool_loop.py` runs Kimi in a tool loop with these tools. |
| 3 | `open_browser` tool: Playwright + Chrome user data dir + Tavily fallback. | Smoke script opens a JS-heavy page and extracts markdown. Visual: Chrome window opens. |
| 4 | `agentic_member_turn` + `ToolBudget` in `orchestrator.py`. Strategist and Researcher prompts get Research Protocol sections. | CLI: `--members strategist,researcher --depth deep "Q"` runs both agentically with visible tool events. |
| 5 | Chair intake (`intake.py` + `chair_intake.md`). | CLI: ambiguous query triggers clarifying questions; clear query routes immediately. |
| 6 | Live `script="live_research"` path: intake → first round → secretary brief. Other members run `mode=fast`. | End-to-end CLI demo runs in <10 minutes. Asciinema recording captured. |
| 7 | Polish: error paths, documentation, demo script. | Demo runs cleanly 3 times from clean state. |

### Phase 2 — week 2–3

- All seven members upgraded.
- Mid-deliberation follow-up channel.
- Web UI streams tool events.
- `validate_claim` tool.
- Role-tuned tool subsets.
- Secretary `## Sources` section.

### Phase 3 — week 4

- Harness ledger persists tool calls.
- Cost dashboard.
- Failure-mode test suite.
- Adaptive depth tuning loop.

## 7. Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Chrome profile collision with user's running Chrome | High | Demo-blocking | Detect on launch; surface clear message; document need to close Chrome OR set `AGENTIC_BOARD_BROWSER=tavily` |
| Kimi/DeepSeek tool-calling quirk | Medium | Day-1 blocker | Test on day 1; if blocked, swap chair to deepseek (single provider for both chair and council in Phase 1; verifier decoupling check is bypassable via `AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1` for the demo branch) |
| Two members in parallel → 2 Chrome windows | Medium | UX | Process-wide semaphore of 1 on `open_browser`; queues serialize |
| `ask_user` deadlocks in non-tty CLI | Low | Demo break | Detect tty; in non-tty, return `[NO_USER_RESPONSE]` and continue |
| Demo wall-clock exceeds 10 min | Medium | Demo pacing | Phase 1 deep-mode caps: 3 tool calls, 180s per member |
| RoutingDecision JSON malformed | Medium | Falls back gracefully | `DEFAULT_ROUTING` from existing classifier output |
| Playwright not installed on demo machine | Medium | Browser tool fails | `AGENTIC_BOARD_BROWSER=tavily` fallback + install instructions in demo README |

## 8. Open questions (to resolve during Phase 1)

1. **Demo machine readiness**: which OS will the demo run on? (Determines Chrome profile path resolution and headed-mode quirks.) — answer needed by day 6.
2. **Tavily API key for demo**: confirmed available? — needed by day 1.
3. **Chair intake max clarifications**: 3 is the cap. If user always declines to answer, intake should still emit a routing decision (with explicit `[USER_DECLINED]` markers in `interpreted_query`). Loop bound is 3, not budget-only.
4. **Secretary `## Sources` section**: ship in Phase 1 day 7 if time permits, else Phase 2.

## 9. Out-of-scope confirmations

- No MCP servers (direct Playwright).
- No cloud browser services.
- No multi-tenant browser pools.
- No source quality scoring.
- No replacement of the four-stage flow; both scripts coexist.
- No member identity/role rewrites; only Research Protocol additions.

## 10. References

- Existing infrastructure to integrate with:
  - `server/execution/web_search.py` — wrapped by `web_search` tool.
  - `server/execution/evidence.py` — used by `web_search` tool for packet persistence.
  - `server/board/deliberation/live.py` — gains scripts.
  - `server/board/deliberation/orchestrator.py` — gains `agentic_member_turn`.
  - `server/board/deliberation/classifier.py` — kept as legacy fallback.
  - `server/protocols/stage1_independent.md` — small note about tools.
- Design influences:
  - Existing four-stage flow architecture.
  - The recently shipped `secretary-multiround` work (`docs/superpowers/specs/2026-05-03-secretary-flow-multiround-design.md`).
  - Playwright MCP and `browser-use` patterns considered and rejected for this scope.
