# LLM Provider Selection & Configuration Guidebook

**Date:** 2026-04-25
**Audience:** Operators of Agentic Board choosing model defaults, debugging
provider behavior, or expanding the council.
**Scope:** The five providers wired into `server/board/llm.py`
(Qwen, DeepSeek, Moonshot/Kimi, Z.AI/GLM, Gemini) plus OpenRouter as an
opt-in escape hatch.

> Source data is current as of April 2026 and was synthesized from each
> provider's official docs. Pricing changes frequently and previews come
> and go — verify the URLs cited at the bottom of each section before
> committing to a default.

---

## 1 — How to read this guidebook

The Agentic Board uses several distinct LLM roles:

| Role                 | What it does                                    | Failure mode if wrong model |
| -------------------- | ----------------------------------------------- | --------------------------- |
| **Chairperson**      | Synthesizes Stage 3 board decision              | Shallow synthesis; hallucinated certainty |
| **Council members**  | Stage 1 independent analysis + Stage 2 peer review | Generic answers; weak push-back |
| **Classifier**       | Picks which members to invoke per query         | Wrong members → wasted tokens |
| **Verifier**         | Stage 4 quality gate (must be a different provider than chairperson) | Rubber-stamp approval |

Pick a model per role, then set the env vars in `.env`:

```bash
CHAIRMAN_MODEL=...
COUNCIL_MODELS=<comma-separated>
CLASSIFIER_MODEL=...
VERIFICATION_MODEL=...
```

Defaults in `server/board/config.py` use `kimi/kimi-k2.6` (chairperson),
`[deepseek-v4-pro, glm-5.1, qwen3.6-max-preview]` (council),
`gemini/gemini-2.5-flash` (classifier — free tier), and
`deepseek/deepseek-v4-pro` (verifier — different provider from chairperson).
A brand-new install with all defaults active needs `MOONSHOT_API_KEY`,
`DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `DASHSCOPE_API_KEY` (with
`DASHSCOPE_REGION=international`), and `GEMINI_API_KEY`.

---

## 2 — Quick-start setups

Three pre-tuned configurations to get you running.

### 2a. Free-only setup (zero cost)

Best for evaluation, tinkering, low-volume demos. Rate-limited but
no per-token cost.

```bash
GEMINI_API_KEY=...                  # AI Studio: https://aistudio.google.com/apikey
ZAI_API_KEY=...                     # https://docs.z.ai
DASHSCOPE_API_KEY=...
DASHSCOPE_REGION=international      # REQUIRED for Qwen free quota

CHAIRMAN_MODEL=gemini/gemini-2.5-pro                  # paid in this tier
# (No fully-free chairperson — see "free chairperson?" below)
COUNCIL_MODELS=gemini/gemini-2.5-flash,glm/glm-4.5-flash,qwen/qwen-flash
CLASSIFIER_MODEL=glm/glm-4.5-flash
VERIFICATION_MODEL=qwen/qwen-flash
```

> **Free-tier honest caveat.** The strongest models (Gemini 2.5/3 Pro,
> GLM-5.1, Qwen 3-Max, Kimi K2.6) are paid. A truly zero-cost chairperson
> means using a `*-flash` tier as the synthesizer — quality drops noticeably.
> Expect to spend ~$0.50/run if you put one paid model in the chairperson
> seat.

### 2b. Low-cost setup (≈$1–3 per deliberation)

Mix of paid mid-tier models. Free-tier fallbacks still kick in if a
primary fails.

```bash
GEMINI_API_KEY=...
ZAI_API_KEY=...
DASHSCOPE_API_KEY=...
DASHSCOPE_REGION=international
DEEPSEEK_API_KEY=...
MOONSHOT_API_KEY=...

CHAIRMAN_MODEL=kimi/kimi-k2.6                         # ≈ $0.95/$4.00 per 1M
COUNCIL_MODELS=deepseek/deepseek-chat,qwen/qwen-plus,glm/glm-4.6
CLASSIFIER_MODEL=deepseek/deepseek-chat               # cheapest reliable
VERIFICATION_MODEL=gemini/gemini-2.5-flash            # different provider ✓
```

### 2c. Premium setup (deepest reasoning, highest cost)

```bash
CHAIRMAN_MODEL=gemini/gemini-2.5-pro                  # or gemini-3-pro-preview
COUNCIL_MODELS=kimi/kimi-k2.6,deepseek/deepseek-v4-pro,qwen/qwen3-max,glm/glm-5.1
CLASSIFIER_MODEL=deepseek/deepseek-chat
VERIFICATION_MODEL=glm/glm-5                          # different from chairperson
```

Expect ~$5–10 per multi-stage deliberation depending on how chatty the
members are.

---

## 3 — Provider summaries

### 3a. Z.AI / GLM (Zhipu BigModel)

**Routing:** `glm/<id>` or `zai/<id>` → native `zai-sdk` SDK.
**Auth:** `ZAI_API_KEY`.

| Model ID            | Tier   | Strength                                            | Context | Max out | Thinking | $ in / $ out / 1M tok    |
| ------------------- | ------ | --------------------------------------------------- | ------- | ------- | -------- | ------------------------ |
| `glm-5.1`           | Paid   | 8-hour autonomous tasks; deep reasoning             | 200k    | 128k    | yes      | $1.40 / $4.40            |
| `glm-5-turbo`       | Paid   | Fast agentic loop; balanced                         | 202k    | 16k     | yes      | $1.20 / $4.00            |
| `glm-5`             | Paid   | General reasoning                                   | 202k    | 16k     | yes      | $0.50 / $2.08            |
| `glm-4.7`           | Paid   | Agentic coding, task completion                     | 200k    | 128k    | yes      | (contact)                |
| `glm-4.7-flashx`    | Paid   | Lightweight, high-throughput                        | 200k    | 128k    | yes      | $0.07 / $0.40            |
| `glm-4.7-flash`     | **Free** | Low-latency chat / coding                         | 200k    | 128k    | yes      | $0 / $0                  |
| `glm-4.6`           | Paid   | Real-world coding (74 Claude Code benchmarks)       | 200k    | 128k    | yes      | $0.60 / $2.20 (approx)   |
| `glm-4.5`           | Paid   | Agentic AI baseline                                 | 128k    | 96k     | yes      | $0.20–0.60 / $1.10–2.20  |
| `glm-4.5-air`       | Paid   | Lightweight                                         | 131k    | 98k     | yes      | $0.13 / $0.85            |
| `glm-4.5-flash`     | **Free** | Free-tier entry point                             | 128k    | 96k     | yes      | $0 / $0                  |

**Quirks:**

- Default temperature varies: GLM-5 family uses **1.0**, GLM-4.5 family uses **0.6**.
- `thinking={"type": "enabled"}` is the default for GLM-4.5+; pass
  `{"type": "disabled"}` to turn off (we expose this via `ZAI_THINKING`
  env).
- Reasoning tokens stream as `delta.reasoning_content` (separate from
  `delta.content`).

**Sources:** [Z.AI pricing](https://docs.z.ai/guides/overview/pricing) ·
[GLM-5.1](https://docs.z.ai/guides/llm/glm-5.1) ·
[GLM-4.6](https://docs.z.ai/guides/llm/glm-4.6) ·
[Bigmodel intro (CN)](https://docs.bigmodel.cn/cn/guide/start/introduction)

### 3b. Gemini (Google AI Studio)

**Routing:** `gemini/<id>` → `google-genai` SDK.
**Auth:** `GEMINI_API_KEY` (or `GOOGLE_API_KEY` as fallback).

| Model ID                          | Tier            | Strength                       | Context | Max out | Thinking            | $ in / $ out / 1M tok |
| --------------------------------- | --------------- | ------------------------------ | ------- | ------- | ------------------- | --------------------- |
| `gemini-3-pro-preview`            | Free + Paid     | Deepest reasoning (2026)       | 1M      | 65k     | forced (`thinking_level`) | $2–4 / $12–18        |
| `gemini-3-flash-preview`          | Free + Paid     | Fast multimodal                | 1M      | 65k     | forced              | ~$0.10–0.40 / ~$0.40–1.20 |
| `gemini-3-flash-lite-preview`     | Free + Paid     | Cheapest routing/classifier    | 1M      | 65k     | forced (low)        | $0.25 / $1.50         |
| `gemini-2.5-pro`                  | Paid            | Deep reasoning + thinking budget | 1M    | 65k     | yes (`thinking_budget` 0–32k or `-1` dynamic) | $2.00 / $12.00 |
| `gemini-2.5-flash`                | **Free** + Paid | Best free-tier all-rounder     | 1M      | 65k     | yes (`-1` dynamic)  | Paid: $0.30 / $2.50; Free: rate-limited |
| `gemini-2.5-flash-lite`           | Paid            | Cheapest 2.5 multimodal        | 1M      | 65k     | yes                 | $0.10 / $0.40         |

> **Model-name caveat.** Google's preview model IDs change formatting often
> (`gemini-3-pro-preview` vs `gemini-3.1-pro-preview` vs `…-preview-1`).
> Always confirm against the [official models page](https://ai.google.dev/gemini-api/docs/models)
> before committing it to `.env`.

**Free-tier rate limits** (verify per project at AI Studio dashboard;
typical defaults):

- 5–15 RPM, 100–1000 RPD per model
- Universal cap: **250k tokens/min** across all free models

**Quirks:**

- System prompt → `GenerateContentConfig.system_instruction` (NOT inside
  `contents`). The handler in `llm.py` already routes correctly.
- `max_output_tokens` (not `max_tokens`).
- Role mapping: `assistant → "model"`. Handled by `_GEMINI_ROLE_MAP`.
- 2.5 models: `thinking_config={"thinking_budget": <int>}` —
  `0` disables, `-1` enables dynamic.
- 3.x models: `thinking_level="minimal"|"low"|"medium"|"high"` — cannot
  fully disable.
- Default temperature: `1.0`. Range `[0.0, 2.0]`.

**Sources:** [Gemini API models](https://ai.google.dev/gemini-api/docs/models) ·
[Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) ·
[Thinking config](https://ai.google.dev/gemini-api/docs/thinking) ·
[Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)

### 3c. Qwen (Alibaba Model Studio / DashScope)

**Routing:** `qwen/<id>` → native `dashscope` SDK.
**Auth:** `DASHSCOPE_API_KEY`.
**Region:** Set `DASHSCOPE_REGION=international` (Singapore endpoint) for
the free quota — the default `cn` has no free tier.

> Model ID rendering varies in Alibaba's docs (some pages use dotted
> versions like `qwen3.5-plus`, others use hyphens). The hyphen form
> mirrored below is what most 2026 docs and the DashScope SDK accept;
> always verify before deploying.

| Model ID                      | Tier                          | Strength                                         | Context | Thinking                  | $ in / $ out / 1M tok |
| ----------------------------- | ----------------------------- | ------------------------------------------------ | ------- | ------------------------- | --------------------- |
| **Qwen 3.6 series (2026-04)**  |                               |                                                  |         |                           |                       |
| `qwen3.6-max-preview`          | Paid                          | 2026 flagship; #1 SWE-bench Pro/Terminal-Bench 2.0/SkillsBench | 260k    | yes + `preserve_thinking` | $1.30 / $7.80         |
| `qwen3.6-plus`                 | Paid                          | Production agentic coding; 78.8% SWE-Bench       | 1M      | yes + `preserve_thinking` | $0.325 / $1.95        |
| `qwen3.6-plus-2026-04-02`      | Paid                          | Dated snapshot of plus                             | 1M      | yes + `preserve_thinking` | $0.325 / $1.95        |
| `qwen3.6-flash`                | Paid + free quota             | Fast, cheap responder                              | 1M      | yes                        | $0.065 / $0.26 / free  |
| `qwen3.6-flash-2026-04-16`     | Paid + free quota             | Dated snapshot of flash                            | 1M      | yes                        | $0.065 / $0.26 / free  |
| `qwen3.6-27b`                  | Open-weight (Apache 2.0)      | Dense; multimodal; 262k → 1M extensible           | 262k    | yes (Thinking Preservation)| self-host            |
| `qwen3.6-35b-a3b`              | Open-weight (Apache 2.0)      | MoE variant; efficient inference                  | (vary)  | yes                        | self-host            |
| **Qwen 3.5 series**            |                               |                                                  |         |                           |                       |
| `qwen3-max`                    | Paid                          | Most capable; complex reasoning                   | 262k    | yes                        | $0.78 / $3.90         |
| `qwen3.5-plus`                 | Paid                          | Balanced cost/capability                          | 1M      | yes                        | $0.26 / $1.56         |
| `qwen3.5-plus-2026-02-15`      | Paid                          | Dated snapshot of plus                             | 1M      | yes                        | $0.26 / $1.56         |
| `qwen3.5-plus-2026-04-20`      | Paid                          | Dated snapshot of plus                             | 1M      | yes                        | $0.26 / $1.56         |
| `qwen3.5-flash-2026-02-23`     | Paid + free quota             | Dated flash snapshot                               | 1M      | yes                        | $0.065 / $0.26 / free  |
| `qwen3.5-27b`                  | Open-weight (Apache 2.0)      | Dense open-weight                                  | (vary)  | yes                        | self-host            |
| `qwen3.5-35b-a3b`              | Open-weight (Apache 2.0)      | MoE open-weight                                   | (vary)  | yes                        | self-host            |
| `qwen3.5-122b-a10b`            | Open-weight (Apache 2.0)      | Large MoE; high capacity                          | (vary)  | yes                        | self-host            |
| `qwen3.5-397b-a17b`            | Open-weight (Apache 2.0)      | Ultra-large MoE; frontier research                | (vary)  | yes                        | self-host            |
| **Legacy models**              |                               |                                                  |         |                           |                       |
| `qwen3-coder`                  | Paid                          | Coding agent (69.6% SWE-Bench)                    | (vary)  | hybrid                     | (varies)             |
| `qwen3-vl`                     | Paid                          | Vision-language reasoning                         | 256k–1M | yes                        | $0.117 / $1.365       |
| `qwen-long`                    | Paid                          | 10M-token long context                            | 10M     | no                         | premium               |
| `qwen-flash`                   | Paid + free quota             | Latency-optimized chat                             | 1M      | optional                   | (low) / free quota    |
| `qwen-turbo`                   | Paid + free quota             | Cost-optimized                                    | 1M      | optional                   | $0.05 / $0.20 / free  |

**Free quota:** New international/Singapore accounts get 1M input + 1M
output tokens free for **90 days** after Model Studio activation.
US-Virginia (`global`) has **no** free quota.

**Quirks:**

- DashScope returns errors as response objects (`status_code >= 400`),
  not exceptions. The handler in `llm.py` raises `LLMProviderError`
  proactively for these.
- Pass `result_format="message"` to get the OpenAI-shaped response.
- Thinking: `enable_thinking=True` + optional `thinking_budget=<int>`
  (max thinking tokens). Wired up via `QWEN_THINKING` /
  `QWEN_THINKING_BUDGET` env vars.
- Default temperature: model-dependent; range `[0, 2)`. The `dashscope`
  SDK quietly accepts a wider range than other providers.
- `qwen3.6-*` introduces `preserve_thinking=bool` for multi-turn agentic
  flows (preserves prior thinking traces across turns). Wired up via
  `QWEN_PRESERVE_THINKING` env. Older models silently ignore the kwarg.
- `qwen3.6-*` is also exposed via Alibaba Cloud's compatible-mode endpoint
  with both OpenAI and Anthropic API shapes — but the board uses the
  native DashScope path, not compatible-mode.

**Sources:**
[Models overview (Bailian Console)](https://bailian.console.aliyun.com/cn-beijing/?tab=model#/model-market) ·
[DashScope SDK](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope) ·
[Pricing](https://www.alibabacloud.com/help/en/model-studio/billing-of-model-studio)

### 3d. DeepSeek

**Routing:** `deepseek/<id>` → `openai` SDK + `https://api.deepseek.com/v1`.
**Auth:** `DEEPSEEK_API_KEY`.
**Docs:** [Pricing](https://api-docs.deepseek.com/quick_start/pricing) |
[Chat API](https://api-docs.deepseek.com/api/create-chat-completion) |
[Thinking mode](https://api-docs.deepseek.com/guides/thinking_mode)

| Model ID                    | Tier    | Strength                                              | Context | Max out | Thinking / Reasoning                     | $ in* / $ out* per 1M tok (cache-miss) |
| --------------------------- | ------- | ----------------------------------------------------- | ------- | ------- | ---------------------------------------- | -------------------------------------- |
| **V4 series (current)**     |         |                                                       |         |         |                                          |                                        |
| `deepseek-v4-flash`         | Paid    | General chat, coding, fast responder                  | 1M      | 384k    | optional (`reasoning_effort`)            | ~$0.14 / ~$0.28  (¥1/¥2 CNY)         |
| `deepseek-v4-pro`           | Paid    | Hardest reasoning, math, logic, agentic tasks          | 1M      | 384k    | default high; supports `"max"` effort    | **Promo** $0.435 / $0.87 (¥3/¥6); **Full** $1.74 / $3.48 (¥12/¥24) |
| **Legacy aliases ⚠️**       |         | *(retire **2026-07-24**; now route to v4-flash under hood)* |       |         |                                          |                                        |
| `deepsearch-chat`           | Legacy  | Alias → v4-flash **non-thinking** mode                | 1M      | 384k    | disabled                                 | same as v4-flash                        |
| `deepseek-reasoner`         | Legacy  | Alias → v4-flash **thinking** mode                   | 1M      | 384k    | enabled                                  | same as v4-flash                        |

*\*Cache-hit input costs ~98% less (v4-flash: ¥0.02/M; v4-pro: ¥0.025/M). Off-peak windows (UTC 16:30–00:30) may have further discounts.*

> **Pricing note — V4-Pro promo.** The 75% discount (**$0.435/$0.87** instead of full **$1.74/$3.48**) expires **2026-05-05 23:59 Beijing time**. After that the full rate applies. Plan accordingly if you pin `deepseek-v4-pro` as a council or verifier model.
>
> **Currency.** DeepSeek bills in **CNY (RMB)**. USD equivalents above use ~7.2 CNY/USD and are approximate.

**Features (V4 models):**
- JSON Output mode (`response_format={"type": "json_object"}`)
- Tool Calls / function calling
- Conversation prefix continuation (Beta)
- FIM (Fill-In-the-Middle) completion (Beta, non-thinking only)
- Anthropic-compatible endpoint at `https://api.deepseek.com/anthropic`

**Deprecation timeline:**

| Model / Event          | Date        | Action                              |
| ---------------------- | ----------- | ----------------------------------- |
| v4-pro 75% promo ends  | 2026-05-05  | Price jumps to $1.74/$3.48          |
| Kimi K2 (original) retires | 2026-05-25 | Migrate to k2.6                   |
| Gemini 2.0 Flash retires   | 2026-06-01 | Migrate to 2.5/3 family           |
| `deepseek-chat` alias retires  | 2026-07-24 | Use `deepseek-v4-flash` instead  |
| `deepseek-reasoner` alias retires | 2026-07-24 | Use `deepseek-v4-pro` (thinking) or v4-flash instead |

**Quirks:**

- Thinking/reasoner modes **silently ignore** `temperature`, `top_p`,
  `frequency_penalty`, `presence_penalty`. The handler already drops
  `temperature` for reasoner-style calls.
- Reasoning chain-of-thought returned in
  `response.choices[0].message.reasoning_content` (separate from
  `content`). The board does not currently capture this as a separate
  metric.
- Thinking control for V4: `reasoning_effort="low"|"medium"|"high"|"max"`.

**Sources:**
[Pricing](https://api-docs.deepseek.com/quick_start/pricing) ·
[Chat completion API](https://api-docs.deepseek.com/api/create-chat-completion) ·
[Thinking guide](https://api-docs.deepseek.com/guides/thinking_mode) ·
[Changelog](https://api-docs.deepseek.com/updates)

### 3e. Moonshot Kimi

**Routing:** `kimi/<id>` (or `moonshot/<id>`) → `openai` SDK +
`https://api.moonshot.ai/v1` (note `.ai`, not the older `.cn`).
**Auth:** `MOONSHOT_API_KEY`.

| Model ID            | Strength                              | Context | Max out | Thinking      | $ in / $ out / 1M tok |
| ------------------- | ------------------------------------- | ------- | ------- | ------------- | --------------------- |
| `kimi-k2.6`         | Agentic coding, long-context (current) | 256k    | 65.5k   | default on    | $0.95 / $4.00         |
| `kimi-k2.5` ⚠       | Deep reasoning + CoT                  | 262k    | 65.5k   | yes (fixed temp) | $0.60 / $3.00         |
| `kimi-k2-thinking`  | Extended multi-step reasoning         | 256k    | 65.5k   | required (temp 1.0) | ~$1.50 / $6.00     |
| `moonshot-v1-128k`  | General-purpose chat (cheaper)        | 128k    | 32k     | no            | ~$0.15 / $0.60        |

> ⚠ **Deprecation:** Original Kimi K2 retires **2026-05-25**. K2.6
> (released 2026-04-20) is the current flagship. K2.5 still supported
> but plan to migrate. The board's default chairperson is
> `kimi/kimi-k2.6` (switched 2026-04-25).

**Quirks (very important):**

- `kimi-k2.5` and `kimi-k2.6` both reject `temperature` entirely — must omit.
  The handler enforces this (`startswith(("kimi-k2.5", "kimi-k2.6")) → omit temperature`).
  `kimi-k2-thinking` locks temperature at 1.0.
- Other Kimi models accept caller's temperature (default 0.6, range
  `[0, 1]` — narrower than OpenAI's `[0, 2]`).
- `top_p` is locked at `0.95` for K2.5/K2.6 — don't override.
- `n` must be `1` (no multiple completions) for K2.5/K2.6.
- Thinking mode parameter:
  `extra_body={"thinking": {"type": "enabled"|"disabled"}}` (wired up
  via `KIMI_THINKING` env).
- Tool choice: when thinking is enabled, only `tool_choice="auto"` or
  `"none"` are valid (no `"required"`).
- Older `.cn` domain still works for legacy CN accounts; `.ai` is the
  current canonical endpoint.

**Sources:**
[Models](https://platform.kimi.ai/docs/intro/models) ·
[Pricing](https://platform.kimi.ai/docs/pricing/chat) ·
[K2.6 quickstart](https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart) ·
[OpenAI-to-Kimi migration](https://platform.moonshot.ai/docs/guide/migrating-from-openai-to-kimi)

---

## 4 — Recommendations by board role

Cross-provider mapping for each role under the three setups in §2.

| Role           | Free-only setup        | Low-cost setup           | Premium setup                  |
| -------------- | ---------------------- | ------------------------ | ------------------------------ |
| Chairperson    | `gemini/gemini-2.5-pro` (cheapest paid) | `kimi/kimi-k2.6`         | `gemini/gemini-2.5-pro` or `gemini/gemini-3-pro-preview` |
| Strategist     | `gemini/gemini-2.5-flash` | `deepseek/deepseek-v4-pro` | `kimi/kimi-k2.6`              |
| Product Lead   | `glm/glm-4.5-flash`    | `qwen/qwen3.5-plus`      | `glm/glm-5.1`                  |
| Researcher     | `qwen/qwen-flash`      | `glm/glm-4.6`            | `qwen/qwen3-max`               |
| Critic         | `gemini/gemini-2.5-flash` | `gemini/gemini-2.5-pro` | `gemini/gemini-2.5-pro` (thinking) |
| Architect/Builder | `qwen/qwen-flash`   | `qwen/qwen3-coder`       | `qwen/qwen3-coder` + `kimi/kimi-k2.6` (parallel) |
| Classifier     | `glm/glm-4.5-flash`    | `deepseek/deepseek-chat` | `gemini/gemini-3-flash-lite-preview` |
| Verifier       | `qwen/qwen-flash` *    | `gemini/gemini-2.5-flash` | `glm/glm-5`                   |

\* Verifier MUST be a different provider than chairperson — see §6.

**2026-04 project defaults** (`server/board/config.py`):
Chairperson `kimi/kimi-k2.6` · Council `[deepseek-v4-pro, glm-5.1, qwen3.6-max-preview]` ·
Classifier `gemini/gemini-2.5-flash` · Verifier `deepseek/deepseek-v4-pro`.

---

## 5 — Token configuration cheatsheet

What you can/can't pass to each provider's chat-completion call.

| Provider   | `max_tokens` field          | `temperature` default & range  | Thinking control                   | Notes                          |
| ---------- | --------------------------- | ------------------------------ | ---------------------------------- | ------------------------------ |
| Gemini     | `max_output_tokens`         | `1.0`, `[0, 2]`                | 2.5: `thinking_budget` (-1/0/0–32k); 3.x: `thinking_level` (min/low/med/high) | system → `system_instruction` |
| Z.AI/GLM   | `max_tokens`                | `0.6` (4.5) or `1.0` (5+); `[0, 1]` | `thinking={"type": "enabled"\|"disabled"}` | reasoning streams as `reasoning_content` |
| Qwen       | `max_tokens`                | model-specific; `[0, 2)`       | `enable_thinking=bool`, `thinking_budget=int` | errors come back IN-band       |
| DeepSeek   | `max_tokens`                | `1.0`, `[0, 2]`; ignored in thinking mode | `reasoning_effort="high"\|"max"` | reasoner ignores temp/top_p     |
| Kimi       | `max_tokens`                | K2.5: omit; K2-thinking: 1.0; others: `0.6`, `[0, 1]` | `extra_body={"thinking": {"type": ...}}` | `top_p` locked, `n=1` only      |
| OpenRouter | `max_tokens`                | `1.0`, `[0, 2]`                | model-passthrough                  | escape hatch via `openrouter:` prefix |

**The board's defaults**:

```python
# server/board/llm.py
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 8192    # was 4096; bumped for reasoning-model headroom
DEFAULT_TIMEOUT = 240.0      # was 120.0; deep reasoning takes 60-90s
```

These are caller-agnostic — each provider's handler post-processes them
to honour the per-model rules above.

---

## 6 — Verifier decoupling

The board enforces that **`VERIFICATION_MODEL` and `CHAIRMAN_MODEL` must
use different providers**. This is a guard against rubber-stamp
verification (a chairperson's blind spots are often shared by other
models from the same family).

`server/board/config.py:_assert_verifier_decoupled()` checks at boot.
Provider is detected via prefix:

| Chairperson           | Valid verifier prefixes                       |
| --------------------- | --------------------------------------------- |
| `gemini/...`          | `glm/`, `zai/`, `qwen/`, `deepseek/`, `kimi/`, `moonshot/` |
| `glm/...` / `zai/...` | `gemini/`, `qwen/`, `deepseek/`, `kimi/`, `moonshot/` |
| `qwen/...`            | `gemini/`, `glm/`, `zai/`, `deepseek/`, `kimi/`, `moonshot/` |
| `deepseek/...`        | `gemini/`, `glm/`, `zai/`, `qwen/`, `kimi/`, `moonshot/` |
| `kimi/...` / `moonshot/...` | `gemini/`, `glm/`, `zai/`, `qwen/`, `deepseek/` |

For one-off experimentation only, set
`AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1` to bypass.

---

## 7 — Free-first fallback chain

When a primary call raises `LLMProviderError`,
`server/board/llm.py:query_llm()` walks this chain (skipping any entry
whose env var is missing, whose region isn't free-eligible, or whose
prefix matches the failed primary):

1. `gemini/gemini-2.5-flash` (free)
2. `glm/glm-4.5-flash` (free)
3. `qwen/qwen-flash` (free quota — Singapore region only)
4. `deepseek/deepseek-chat` (paid — last resort)

To get the most out of the free portion of this chain:

- Set `GEMINI_API_KEY`.
- Set `ZAI_API_KEY`.
- Set `DASHSCOPE_API_KEY` AND `DASHSCOPE_REGION=international`.

Without the region setting, Qwen is silently skipped — `cn` (the SDK's
default) has no free quota.

`fallback=False` on a single `query_llm` call disables the chain and
re-raises the primary error directly.

**Latency envelope.** With the post-2026-04-25 defaults (`max_tokens=8192`,
`timeout=240s`, `PRIMARY_MAX_RETRIES=3`, `FALLBACK_MAX_RETRIES=2`), a single
`query_llm` call can block up to ~44 minutes worst-case before raising
(primary 720s + 3 free fallbacks × 480s + paid last-resort 480s, plus
~21s of retry backoffs). Operators behind reverse proxies with short
gateway timeouts should either lower `PRIMARY_MAX_RETRIES`, pass
`fallback=False` for latency-sensitive call sites, or set their own
upstream timeouts. The verifier and classifier handlers in
`server/board/deliberation/{verification.py,classifier.py}` already pin
their own shorter timeouts to avoid this.

---

## 8 — Common gotchas

- **Kimi temperature errors.** Passing `temperature` to `kimi-k2.5` will
  return a 400. The handler protects you, but if you call the SDK
  directly bypassing the handler, omit temperature. Same for
  `kimi-k2-thinking` (it locks at 1.0).
- **DeepSeek reasoner ignores params.** `temperature`, `top_p`,
  `frequency_penalty`, `presence_penalty` are silently dropped in
  thinking mode. Tune behavior via `reasoning_effort` instead.
- **Qwen free-quota gate.** Default `DASHSCOPE_REGION=cn` → no free
  tier. Set `=international` (alias `singapore`) to enable.
- **Moonshot domain change.** Default `MOONSHOT_BASE_URL` is now
  `https://api.moonshot.ai/v1` (was `.cn`). Legacy `.cn` still works
  for some accounts; if your existing `.cn` key fails, switch to `.ai`.
- **Gemini auth precedence.** `GEMINI_API_KEY` wins over `GOOGLE_API_KEY`
  when both are set. `.env.example` documents this.
- **Chairperson via OpenRouter.** Use the `openrouter:<provider>/<model>`
  prefix explicitly — bare `provider/model` ids no longer route to
  OpenRouter (this was a deliberate breaking change in the 2026-04
  refactor).
- **Deprecation timeline:** track these dates so models don't disappear
  out from under you:
  - DeepSeek `deepseek-chat`, `deepseek-reasoner` aliases: **2026-07-24**
  - Kimi K2 (original): **2026-05-25**
  - Gemini 2.0 Flash family: **2026-06-01**
  - DeepSeek v4-pro 75% promo: **ends 2026-05-05**
- **Qwen `qwen3.6-max-preview` is a preview model.** Alibaba previews
  have historically been promoted to a stable id (e.g., `qwen3.6-max`)
  within ~60 days. Watch the changelog before pinning it for production;
  `qwen/qwen3.6-plus` is the production-grade fallback.

---

## 9 — How to validate a new model

Before pinning a new model in `.env`, smoke-test it through the live
suite:

```bash
# Set the relevant env var (e.g., GEMINI_API_KEY) first
uv run pytest -m live tests/test_llm_live_smoke.py::test_live_gemini -v
```

Live tests are skipped by default (`addopts = "-m 'not live'"`). They
hit the real API with `max_tokens=8` and `fallback=False` so an error
points at the actual provider, not the chain.

For a heavier test, run a single-member deliberation:

```bash
uv run python -m server.cli --members strategist --budget \
  "Should we ship a free tier for the SaaS launch?"
```

`--budget` prints the per-call token usage and estimated cost from
`server/board/metrics.py`. The cost rates table covers all the
native-prefix model ids documented here (others fall back to a
default rate).

---

## 10 — Where to look when behavior is wrong

| Symptom                                         | First place to check                                                                |
| ----------------------------------------------- | ----------------------------------------------------------------------------------- |
| Auth error after restart                        | `.env` reload (run `set -a; source .env; set +a` in the shell that started the server) |
| Empty responses, no error                       | Token cap (`MAX_OUTPUT_TOKENS` or per-stage limit). Crank `max_tokens`.              |
| Long latency on what should be a fast model     | Verify the prefix. If the primary's prefix is unrecognized, fallback chain runs.    |
| "unknown provider prefix" error                 | A bare `provider/model` id slipped past — prefix it with `openrouter:` or fix.      |
| Verifier and chairperson share provider         | `_assert_verifier_decoupled` raises at boot. Pick a different family.               |
| Cost higher than expected                       | Cache misses + free-tier exhausted? Run `--budget` to break down per-call.          |
| Qwen never reached in fallback chain            | `DASHSCOPE_REGION=cn` — set to `international`.                                    |
| Kimi 400 error with `temperature in body`       | Handler bypass — model is K2.5/K2-thinking. Confirm you're calling `query_llm`, not the SDK directly. |

---

## Appendix — Source data freshness

This guide was synthesized 2026-04-25. For each section, the
authoritative URL is cited inline. Model availability and pricing change
weekly; treat this guide as a starting point, not a permanent reference.
