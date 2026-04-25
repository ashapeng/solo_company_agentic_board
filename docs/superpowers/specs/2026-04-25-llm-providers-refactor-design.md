# LLM Providers Refactor — Design

**Date:** 2026-04-25
**Owner:** Peng
**Scope:** `server/board/llm.py` and tightly coupled callers

## Goal

Replace the OpenRouter-as-default architecture in `server/board/llm.py` with five
first-class native providers — **Qwen, DeepSeek, Moonshot/Kimi, Z.AI/GLM,
Gemini** — using each provider's official inference API. OpenRouter remains
available only as an opt-in escape hatch via the explicit `openrouter:<id>`
prefix. The fallback chain is reshaped to prefer free-tier models first, with
one paid model as a last resort.

## Non-goals

- Streaming. `query_llm()` stays request/response only. (Streaming today happens
  at the orchestrator/SSE layer above this; unchanged.)
- Tool calling, structured output, multimodal. Not used by the board today.
- Cost-aware routing or model selection. Defaults stay literal env-overridable
  ids; no auto-pick logic.
- Replay/harness behavior changes. The monkey-patch points in
  `server/harness/replay.py` keep working because `query_llm` remains the single
  public entry.

## Architecture

`server/board/llm.py` keeps a single public entry:

```python
async def query_llm(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    fallback: bool = True,
) -> LLMResponse: ...
```

Routing is decided by the model id's prefix:

| Prefix                       | Provider           | Transport                       |
| ---------------------------- | ------------------ | ------------------------------- |
| `gemini/<model>`             | Google AI Studio   | `google-genai` SDK (native)     |
| `glm/<model>` / `zai/<model>`| Z.AI / Zhipu       | `zai-sdk` SDK (native)          |
| `qwen/<model>`               | Alibaba DashScope  | `dashscope` SDK (native)        |
| `deepseek/<model>`           | DeepSeek           | `openai` SDK + base_url         |
| `kimi/<model>` / `moonshot/<model>` | Moonshot   | `openai` SDK + base_url         |
| `openrouter:<id>`            | OpenRouter         | `httpx` POST (escape hatch)     |
| anything else                | —                  | `RuntimeError` on unknown prefix |

A small `_PROVIDERS` table maps prefix → handler. `query_llm()` looks the
handler up, dispatches, and gets back an `LLMResponse`. The implicit
"no-prefix → OpenRouter" behavior of the current implementation is **removed**.

### File layout

Single file (`server/board/llm.py`), per-provider handlers kept separate for
navigability:

- `_send_gemini(...)`
- `_send_zai(...)`        (existing, unchanged)
- `_send_qwen(...)`       (rewritten to use native `dashscope` SDK)
- `_send_deepseek(...)`   (split out from current shared helper)
- `_send_kimi(...)`       (split out from current shared helper)
- `_send_openrouter(...)` (existing httpx loop, restricted to `openrouter:` prefix)
- `query_llm(...)`        (router + fallback orchestrator)

No shared `_send_openai_compat()` helper. Slightly more LOC, much easier to scan
top-to-bottom.

### Common shapes

- All handlers are `async def` and return an `LLMResponse`.
- Sync SDKs (Gemini, Z.AI, Qwen `dashscope`) are wrapped with
  `asyncio.to_thread`.
- Handlers translate provider errors into a single internal
  `LLMProviderError` for retryable failures (timeout, 5xx, 429); auth/4xx
  errors are raised directly to fail fast.
- Each handler accepts `max_retries: int` and `backoff_seconds: list[int]`
  parameters, defaulting to `3` / `[1, 2, 4]s`. The router passes these
  defaults for primary calls and a shorter `2` / `[1, 2]s` budget when calling
  a handler as part of the fallback chain.
- Each handler reads its env vars **lazily** — only when actually called. A
  missing key on an unused provider does not block startup.

## Per-provider details

### Gemini — `_send_gemini`

- **Auth:** `GEMINI_API_KEY` (or `GOOGLE_API_KEY`; `GOOGLE_API_KEY` wins if both
  are set, per official SDK behavior).
- **SDK:** `from google import genai`; `client = genai.Client()`.
- **Messages:** convert `messages` to a list of
  `types.Content(role=..., parts=[types.Part(text=...)])`. The role mapping is
  `assistant → "model"`; everything else stays `"user"`. A `system` argument is
  passed via `config.system_instruction`, not as a `Content`.
- **Config:** `types.GenerateContentConfig(system_instruction=system,
  temperature=temperature, max_output_tokens=max_tokens)`.
- **Call:** `client.models.generate_content(model=<provider_model>,
  contents=contents, config=config)` inside `asyncio.to_thread`.
- **Response:** content is `response.text`; tokens are
  `response.usage_metadata.prompt_token_count` /
  `candidates_token_count` (both fields fall back to `-1` on absence).

### Z.AI / GLM — `_send_zai` (mostly unchanged)

- **Auth:** `ZAI_API_KEY`.
- **SDK:** `from zai import ZaiClient`.
- **Call:** `client.chat.completions.create(model=<provider_model>,
  messages=full_messages, temperature=..., max_tokens=...)`. Existing
  `ZAI_THINKING=enabled/disabled` env passes through as
  `thinking={"type": ...}`.
- **Wrap:** `asyncio.to_thread`.
- **Response:** OpenAI-shaped; existing `_choice_message_content` /
  `_usage_tokens` helpers continue to work.

### Qwen — `_send_qwen` (new native path; replaces OpenAI-compat)

- **Auth:** `DASHSCOPE_API_KEY`.
- **SDK:** `from dashscope import Generation`.
- **Region:** `DASHSCOPE_REGION` (default `cn`). When set to
  `international`/`singapore`/`global`/etc, `dashscope` SDK auto-routes — pass
  the value via the SDK's region setter (or `base_http_api_url` if
  `DASHSCOPE_BASE_URL` is set explicitly). The existing `QWEN_BASE_URLS` table
  stays in `llm.py` for the explicit-url override path.
- **Call:** `Generation.call(api_key=..., model=<provider_model>,
  messages=full_messages, result_format="message", temperature=...,
  max_tokens=..., **extra)` where `extra` carries `enable_thinking` /
  `thinking_budget` from the existing `QWEN_THINKING` / `QWEN_THINKING_BUDGET`
  envs.
- **Wrap:** `asyncio.to_thread`.
- **Response:** `response.output.choices[0].message.content`; tokens
  `response.usage.input_tokens` / `output_tokens`.
- **Free-quota note:** the free 1M-in / 1M-out quota is region-locked to the
  Singapore (`international`) endpoint and active for 90 days from account
  activation. If the user wants the Qwen free fallback to be reachable, they
  must set `DASHSCOPE_REGION=international`. Documented in `.env.example`.

### DeepSeek — `_send_deepseek`

- **Auth:** `DEEPSEEK_API_KEY`.
- **Base URL:** default `https://api.deepseek.com/v1` (env override
  `DEEPSEEK_BASE_URL`).
- **SDK:** `from openai import OpenAI`.
- **Call:** standard `client.chat.completions.create(model=<provider_model>,
  messages=full_messages, max_tokens=...)`. `temperature` is included **except
  when `model == "deepseek-reasoner"`** (existing rule preserved).
- **Wrap:** `asyncio.to_thread`.
- **Note:** `deepseek-chat` and `deepseek-reasoner` aliases are slated for
  deprecation **2026-07-24**, becoming aliases of `deepseek-v4-flash`. Out of
  scope for this refactor; revisit when the deprecation date approaches.

### Kimi / Moonshot — `_send_kimi`

- **Auth:** `MOONSHOT_API_KEY`.
- **Base URL:** default **`https://api.moonshot.ai/v1`** (env override
  `MOONSHOT_BASE_URL`). The current code's default
  `https://api.moonshot.cn/v1` is updated to the official `.ai` domain.
- **SDK:** `from openai import OpenAI`.
- **Call:** standard chat-completions. Temperature handling preserved:
  - `model.startswith("kimi-k2-thinking")` → `temperature = 1.0`.
  - `model.startswith("kimi-k2.5")` → omit `temperature` (provider enforces a
    fixed value).
  - Otherwise → pass caller's `temperature`.
- **Thinking:** `KIMI_THINKING=enabled/disabled` → `extra_body={"thinking":
  {"type": "enabled" | "disabled"}}` (existing).
- **Wrap:** `asyncio.to_thread`.

### OpenRouter — `_send_openrouter` (escape hatch)

- **Auth:** `OPENROUTER_API_KEY`.
- **Trigger:** model id must start with `openrouter:`. Anything else → routing
  error. (Removes the prior implicit fall-through.)
- **Transport:** existing `httpx.AsyncClient.post(...)` with
  `HTTP-Referer` / `X-Title` headers. Internal retry loop kept.
- **Model id:** strip the `openrouter:` prefix before sending; the remainder is
  passed verbatim as the `model` field (e.g. `anthropic/claude-opus-4`).

## Free-first fallback chain

When `fallback=True` (default) and the primary handler exhausts its retries
with an `LLMProviderError`, `query_llm()` walks a single global chain:

```python
FREE_FALLBACKS = [
    "gemini/gemini-2.5-flash",   # AI Studio free tier
    "glm/glm-4.5-flash",         # Z.AI free
    "qwen/qwen-flash",           # DashScope free quota (international region only)
]
PAID_LAST_RESORT = "deepseek/deepseek-chat"
```

Walk rules:

1. For each entry in `FREE_FALLBACKS` (in order):
   - **Skip** if the entry's required env var is unset (`GEMINI_API_KEY`,
     `ZAI_API_KEY`, `DASHSCOPE_API_KEY`).
   - **Skip Qwen** if `DASHSCOPE_REGION` is not in the free-quota set
     (`international`, `singapore`).
   - **Skip same-provider** as the failed primary (e.g. a `qwen/qwen-max`
     failure skips the `qwen/qwen-flash` fallback). Compared by the prefix
     returned from `provider_of()`.
   - Otherwise, try the entry with a shorter retry budget: 2 attempts,
     `[1, 2]s` backoff. Return on success.
2. If all free entries are skipped or fail, try `PAID_LAST_RESORT` under the
   same skip rules (env var present, not same-provider).
3. If everything fails, **re-raise the primary's exception**, chained from the
   final fallback error.

`LLMResponse.model` reflects the **actual** model used, not the requested
primary. Metrics (`server/board/metrics.py`) and replay (`server/harness/replay.py`)
already key off `LLMResponse.model`, so substitution is observable downstream.

`fallback=False` skips the chain entirely and re-raises the primary's
exception (current behavior preserved). The current `FALLBACK_MODELS` dict (a
flat one-to-one OpenRouter-id mapping) is **deleted**.

## Environment variables

Required only when the corresponding provider is invoked (lazy):

| Provider   | Required             | Optional                                                           |
| ---------- | -------------------- | ------------------------------------------------------------------ |
| Gemini     | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | —                                                |
| Z.AI       | `ZAI_API_KEY`        | `ZAI_THINKING=enabled\|disabled`                                  |
| Qwen       | `DASHSCOPE_API_KEY`  | `DASHSCOPE_REGION` (default `cn`), `DASHSCOPE_BASE_URL`, `QWEN_THINKING`, `QWEN_THINKING_BUDGET` |
| DeepSeek   | `DEEPSEEK_API_KEY`   | `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/v1`)        |
| Kimi       | `MOONSHOT_API_KEY`   | `MOONSHOT_BASE_URL` (default `https://api.moonshot.ai/v1`), `KIMI_THINKING` |
| OpenRouter | `OPENROUTER_API_KEY` (only when `openrouter:` model used) | —                                |

`AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1` continues to short-circuit
`_assert_verifier_decoupled()`.

### `.env.example` updates

- Add `GEMINI_API_KEY=...` to the required-keys block.
- Add a `gemini/<model>` line in the prefix table comment block.
- Add a comment: `# Set DASHSCOPE_REGION=international for Qwen free quota`.
- Update the `MOONSHOT_BASE_URL` example default to `https://api.moonshot.ai/v1`.
- The free-fallback chain itself isn't documented as user-tunable for v1; it
  lives in `llm.py` constants. Revisit if needed.

## Dependencies (`pyproject.toml`)

Add:

- `google-genai>=1.0,<2.0` (pinned major to absorb churn within `_send_gemini`)

Already present (no change): `openai`, `dashscope`, `zai-sdk`, `httpx`,
`pydantic`, `python-dotenv`.

## Caller / migration impact

- **`server/board/config.py`** — defaults unchanged
  (`kimi/kimi-k2.5`, `deepseek/deepseek-chat`). All five providers reachable; no
  rewiring needed.
- **`server/harness/config_provider.py`** — `provider_of()` is already
  prefix-generic and returns `"gemini"` for `gemini/<model>` automatically.
  Update only its docstring to add a `gemini/...` example for clarity.
- **`server/harness/replay.py`** — no code change. The monkey-patch points
  (`server/harness/replay.py:127-135`, `162-163`) replace `query_llm` itself,
  which remains the single public entry.
- **`server/board/metrics.py`** — pricing dict (currently keyed by OpenRouter
  ids like `google/gemini-2.5-pro`) gets new native-prefix entries:
  - `gemini/gemini-2.5-flash` → `(0.0, 0.0)` (free)
  - `gemini/gemini-2.5-pro` → existing public price
  - `glm/glm-4.5-flash` → `(0.0, 0.0)` (free)
  - `qwen/qwen-flash` → `(0.0, 0.0)` (free quota assumption — flagged in
    comment)
  - `qwen/qwen-max`, `qwen/qwen-plus` → public prices
  - Existing `deepseek/...`, `kimi/...` rows untouched.
  Lookup of `openrouter:<id>` strips the prefix and falls back to the existing
  OpenRouter-keyed entries.
- **Member files** (`server/members/*.md`) — `model_override` values (if any)
  must be native-prefixed. To audit during implementation:
  `grep -rn 'model_override' server/members/`. Replace any bare
  `provider/model` ids with the native-prefix or `openrouter:` form as
  appropriate.
- **Tests** — anything that hardcoded `google/gemini-2.5-pro` or
  `openai/gpt-4.1` for OpenRouter routing must switch to the explicit
  `openrouter:` prefix.

## Testing

### Unit (no network)

`tests/board/test_llm_routing.py`:

- Parametrized prefix dispatch: each prefix routes to its `_send_*` handler.
  Stubs replace the handler and record the call.
- Unknown prefix → `RuntimeError`.
- Bare `provider/model` (no prefix) → `RuntimeError`.
- `openrouter:<id>` strips to `<id>` before sending.

`tests/board/test_llm_fallback.py`:

- Free chain order is `gemini → glm → qwen → deepseek` when all keys present
  and `DASHSCOPE_REGION=international`.
- `GEMINI_API_KEY` unset → Gemini entry is skipped, never invoked.
- `DASHSCOPE_REGION=cn` → Qwen entry is skipped.
- Same-provider skip: primary `qwen/qwen-max` failing skips
  `qwen/qwen-flash`.
- `fallback=False` → no chain walked, primary error re-raised.
- All-fail → primary error re-raised, chained from final fallback error.
- On success, `LLMResponse.model` is the substituted id, not the primary.

`tests/board/test_llm_<provider>.py` (one per handler):

- Stubs the SDK boundary (`genai.Client`, `ZaiClient`, `dashscope.Generation`,
  `OpenAI`, `httpx.AsyncClient`).
- Asserts: env var read; correct kwargs (model, messages, temp/max_tokens,
  system, thinking flags); usage tokens parsed; `LLMResponse.model` reflects
  the originally-requested id.
- Provider-specific edge cases:
  - DeepSeek: `deepseek-reasoner` omits `temperature`.
  - Kimi: `kimi-k2.5` omits `temperature`; `kimi-k2-thinking` forces `1.0`.
  - Gemini: `system` is routed to `config.system_instruction`, not into
    `contents`.

### Live smoke (opt-in)

`tests/board/test_llm_live_smoke.py`, marked `@pytest.mark.live`, skipped by
default. One trivial round-trip per provider with `max_tokens=8`. Skip
individual providers whose key isn't set. Run manually with `pytest -m live`.

No real HTTP in default test runs.

## Risks & mitigations

- **Qwen free quota region trap.** Default `DASHSCOPE_REGION=cn` has no free
  quota. Mitigation: documented in `.env.example`; the fallback chain skips the
  Qwen entry when region isn't free-eligible (no silent paid bills).
- **Kimi domain change (`.cn` → `.ai`).** Existing users with
  `MOONSHOT_BASE_URL=https://api.moonshot.cn/v1` set explicitly will keep their
  override. Users on the default switch transparently. Mitigation: documented;
  if anyone reports auth issues, the `.cn` URL still resolves for legacy
  accounts.
- **`google-genai` SDK churn.** The SDK is still on a 1.x release line in
  2026 with occasional breaking changes between minor versions. Major-pin
  (see Dependencies). Breakage stays isolated to `_send_gemini`.
- **Gemini free-tier rate limits (10 RPM).** Cascading to the Gemini fallback
  during a burst could 429. The existing handler-level retry covers transient
  429 once; chain order moves to GLM next on persistent 429.
- **Member files / tests holding bare OpenRouter ids.** Caught during
  implementation via grep; explicit `openrouter:` prefix required.

## Open questions

None remaining.
