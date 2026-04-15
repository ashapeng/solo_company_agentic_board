# LLM Temperature & Token Budget Guide (Agentic Systems)

Last updated: **March 28, 2026**

This guide focuses on two knobs that dominate agent behavior and cost:

- **Temperature (and related sampling controls)**: how deterministic vs. diverse your agent is.
- **Token budgets**: how you prevent runaway loops, latency spikes, and surprise bills.

It's written for *agentic* systems (tools, multi-step loops, multi-agent pipelines), where "just pick a default" usually fails.

---

## Quick Start (Practical Defaults)

### Temperature defaults by agent role

Use these as starting points; then tune with evals.

| Agent Role / Step | Goal | Start Here |
| --- | --- | --- |
| **Tool caller / extractor** | Deterministic JSON, stable tool selection | `temperature = 0.0–0.2` |
| **Planner** | Structured decomposition with minimal drift | `temperature = 0.2–0.4` |
| **Critic / verifier** | Consistent checking and scoring | `temperature = 0.0–0.3` |
| **Writer / brainstormer** | Many diverse options | `temperature = 0.7–1.0` (or sample multiple) |

Provider ranges differ (see "Provider Notes" below): OpenAI, DeepSeek, and GLM support `0–2`; Anthropic and Moonshot/Kimi commonly document `0–1`; Qwen recommends `0.6–0.7` but the exact range depends on the access interface. **Caution:** Some models enforce exact temperature values — e.g., Kimi K2.5 only accepts `0.6` (instant) or `1.0` (thinking) and rejects all others with a 400 error. Your provider layer must override caller-specified temperatures for such models.

### Token budget defaults (guardrails you should always set)

For every model call in an agent loop:

- Set **explicit output limits** (`max_output_tokens` / `max_tokens`).
- Set **tool call limits** where available (e.g., OpenAI `max_tool_calls`).
- Set **iteration limits** in your orchestrator (max steps, max retries).
- Track actual spend using provider **usage** fields, and hard-stop when budgets are exceeded.

---

## Part 1 — Temperature (Sampling) for Agents

### What temperature actually controls

Temperature is a sampling parameter: it changes how heavily you favor high-probability tokens versus exploring lower-probability tokens. In OpenAI's Responses API, it's described as a value between `0` and `2`, where higher values make output more random and lower values more focused and deterministic. Most providers offer a similar control.  

**Important nuance for agents:** "Low temperature" reduces randomness, but it does not guarantee correctness or full determinism. For example, Anthropic explicitly notes that even with `temperature = 0.0`, results will not be fully deterministic.

### Temperature vs. `top_p`: pick one knob to tune

Many providers recommend adjusting **either** `temperature` **or** `top_p` (nucleus sampling), but not both at the same time:

- OpenAI's Responses API documentation makes this recommendation for `temperature` and `top_p`.
- Moonshot/Kimi's API documentation similarly advises modifying one or the other.

Practical rule:

- Prefer **temperature** when you want "more/less randomness" across the board.
- Prefer **top_p** when you want to bound output to a probability mass (often helpful to avoid extremely rare tokens while still allowing some variety).

### How to tune temperature (measured, not vibes)

For agentic systems, temperature should be treated like any other production hyperparameter: tuned on representative tasks.

1. **Define a success metric** per step (e.g., JSON-valid %, tool-call success %, unit tests pass rate, human preference score).
2. **Run a small sweep** (e.g., `0.0, 0.2, 0.4, 0.7, 1.0`) while keeping prompts and constraints fixed.
3. **Pick the lowest temperature that meets the metric** (lower variance is usually better for agents).
4. If you need diversity, prefer **multiple samples + a low-temp judge** over pushing temperature higher.
5. Use provider features for reproducibility where available (e.g., OpenAI `seed`) during evaluation runs.

### Provider notes (ranges, determinism, special modes)

**OpenAI**

- `temperature`: documented range `0–2` in the Responses API.
- **Reproducibility:** OpenAI documents best-effort deterministic sampling via a `seed` parameter and recommends checking `system_fingerprint` for backend changes.
- `max_output_tokens`: limits total generated tokens and can include "reasoning tokens" (so budget accordingly).

**Anthropic**

- `temperature`: commonly documented range `0.0–1.0`.
- Even at `temperature = 0.0`, outputs are not guaranteed deterministic.
- **Extended thinking:** Anthropic documents that extended thinking is *not compatible* with modifying `temperature` (or `top_k`); budget is controlled via `max_tokens` and a thinking budget.
- **Adaptive thinking (Claude 4.6+):** The fixed `budget_tokens` approach is being replaced with `thinking: {type: "adaptive"}` + `output_config: {effort: "high"}`, letting the model dynamically allocate thinking depth based on task requirements.

**Moonshot / Kimi**

- `temperature`: documented range `0–1` in Moonshot's API reference; Moonshot suggests `0.3` as a default value in examples.
- **Enforced temperature (Kimi K2.5):** Unlike most providers, Moonshot's API **rejects** non-standard temperature values for `kimi-k2.5` with a 400 Bad Request. Only two values are accepted: `0.6` (instant/non-thinking mode) and `1.0` (thinking mode). Any other value — even within the documented 0–1 range — returns `invalid temperature: only 0.6 is allowed for this model`. This is not a recommendation; it is a hard API constraint enforced server-side.
- Moonshot also recommends tuning either `temperature` or `top_p`, not both. Recommended `top_p` is `0.95`.
- Kimi-K2's repository describes how some compatibility layers may transform temperature (e.g., an Anthropic-compatible API mapping); treat cross-provider ports as "needs retuning."

**DeepSeek**

- `temperature`: documented range `0–2`, default `1.0`.
- DeepSeek publishes use-case-specific recommendations (notably higher than most providers):

| Use Case | Recommended Temperature |
| --- | --- |
| Coding / Math | `0.0` |
| Data Cleaning / Analysis | `1.0` |
| General Conversation | `1.3` |
| Translation | `1.3` |
| Creative Writing / Poetry | `1.5` |

- `top_p`: range `0–1`, default `1.0`. Recommends tuning either `temperature` or `top_p`, not both.
- `max_tokens`: limits output tokens; context window up to 64K (DeepSeek-V3) / 128K (DeepSeek-R1).
- **Reasoning models (R1):** DeepSeek-R1 generates multi-step reasoning chains before the final answer. Greedy decoding (`temperature = 0.0`) works for coding/math but is not recommended for general reasoning. The reasoning tokens are visible in the response.
- **Context Caching on Disk:** DeepSeek automatically caches repeated prefixes (no code changes needed). Only identical prefixes from token 0 trigger cache hits. Cache hit tokens are priced at ~90% discount. Design rule: same as OpenAI/Anthropic — put static content first, dynamic content last.

**Qwen (Alibaba Cloud)**

- Qwen's API is accessed via three interfaces: **DashScope** (native, most complete), **OpenAI Chat Completions** (compatible), and **OpenAI Responses API** (with built-in tools).
- `temperature`: recommended `0.7` for standard use. For thinking mode, Qwen3 recommends `0.6` with `top_p = 0.95`.
- `top_p`: range `(0, 1.0]`. Recommends tuning either `temperature` or `top_p`, not both.
- **Thinking mode (`enable_thinking`):** Qwen3 models support a thinking/reasoning mode (similar to Anthropic extended thinking or DeepSeek R1). Controlled via `enable_thinking: true` in the API, or `/think` / `/no_think` soft switches in prompts for per-turn control.
- **Important:** greedy decoding (`temperature = 0.0`) should NOT be used when thinking mode is enabled — it causes performance degradation and endless repetitions.
- Token limits are model-dependent; latest models (qwen3-max) support long context windows.

**GLM / Zhipu AI**

- `temperature`: documented range `0–2`, default `1.0` (GLM-5).
- `top_p`: default `0.95`. Recommended range `0.8–0.95` for balanced diversity and quality.
- Recommends tuning either `temperature` or `top_p`, not both.
- `do_sample` (boolean, default `true`): enables random sampling. When `false`, output is fully greedy.
- `max_tokens`: GLM-5 supports up to 128K output tokens. Recommended minimum: 1024 tokens.
- **Thinking mode:** GLM-4.5+ supports `thinking: {"type": "enabled"}`, which triggers deep reasoning with `reasoning_content` streamed separately. Recommended for complex reasoning and coding tasks.
- Context window: up to 200K (GLM-5).

**Google (Vertex AI / Gemini)**

- `temperature`: documented range `0–2` for Gemini models. Default `1.0`. Google recommends `1.0` as a starting point.
- For **Grounding with Google Search**, Google explicitly recommends `temperature = 1.0` for ideal results.
- `temperature = 0` selects the highest-probability token; if responses are too generic or short, increase temperature; if the model loops infinitely, set temperature to at least `0.1`.

---

## Part 1A — Temperature Recommendations (Agentic Use Cases)

### By task type (single-agent or per-step)

| Task Type | What you want | Start Temp | Notes |
| --- | --- | --- | --- |
| **JSON extraction / schema fill** | Deterministic, valid structure | `0.0–0.2` | Use structured output features; don't rely on temperature alone. |
| **Tool selection** | Stable tool choice | `0.0–0.3` | Add tool-choice constraints when available; cap `max_tool_calls`. |
| **Classification / routing** | Consistent labels | `0.0–0.3` | Sample multiple only if you can reconcile disagreements. |
| **Planning / decomposition** | Coherent plan, minimal drift | `0.2–0.4` | Consider a critic pass at `0.0–0.2`. |
| **Code generation / patches** | Correct syntax, low variance | `0.0–0.3` | If you need diversity, sample multiple and run tests. |
| **Summarization of provided text** | Faithful compression | `0.0–0.3` | Use citations/grounding if your stack supports it. |
| **Brainstorming / ideation** | Many distinct options | `0.7–1.0` | Prefer `n=K` samples + ranker over "one very hot sample". |
| **Marketing / creative** | Novel style, variety | `0.8–1.2` (OpenAI) / `0.7–1.0` (0–1 providers) | Keep a low-temp "brand/safety reviewer" agent. |

### Multi-agent pipelines: "hot generator, cold judge"

A reliable pattern for agentic systems:

1. **Generator** at higher temperature produces multiple candidates.
2. **Judge/Critic** at low temperature selects/edits the best candidate using explicit rubric.

This tends to outperform "single pass at medium temperature" when you care about both diversity *and* quality.

### Thinking mode amplifies the hot/cold pattern

When agents use thinking/reasoning mode (Qwen3 hybrid, Kimi K2, ZhipuAI GLM-5, DeepSeek-reasoner), temperature takes on greater significance because it affects the **reasoning process itself**, not just the final answer:

- **Warm thinking (generator, 0.4–0.5):** Higher temperature during the thinking phase causes the model to explore more diverse reasoning paths. For a planner, this means considering more creative decompositions, alternative allocations, and varied designs. The model generates a richer solution space internally, then converges on the best option.
- **Cold thinking (judge, 0.0–0.1):** Lower temperature during thinking produces systematic, methodical evaluation. The model follows a deterministic path through its critique checklist without flip-flopping between contradictory conclusions.

**Critical constraint — `response_format="json_object"` is incompatible with thinking mode** on all Chinese LLM providers (Qwen, Kimi, ZhipuAI). Some providers put JSON in `reasoning_content` instead of `content`, others produce invalid output or API errors. When you need both structured JSON output AND thinking:

1. **Drop `json_object`** — thinking is the core capability (irreplaceable); JSON structure is a convenience (replicable via prompting + extraction).
2. **Prompt-instruct JSON** — add "Respond with valid JSON only" to the system prompt.
3. **Add extraction fallbacks** — parse the response with `json.loads()`, fall back to `{`/`}` boundary extraction for markdown-wrapped or text-embedded JSON.
4. **Retry on parse failure** — thinking models occasionally wrap JSON in explanation text on the first attempt.

---

## Part 1B — Evidence: Does Temperature Actually Matter?

A common assumption is that temperature dramatically affects LLM output quality. Recent empirical research paints a more nuanced picture.

### The Renze et al. study (2024): "No statistically significant impact"

The most comprehensive empirical study to date (Renze, Johns Hopkins University, 2024) tested **nine popular LLMs across temperatures 0.0 to 1.6** on standard multiple-choice benchmarks. The headline finding: **temperature changes from 0.0 to 1.0 do not have a statistically significant impact on problem-solving performance** for single-pass tasks. The result generalized across different LLMs, prompt-engineering techniques, and problem domains.

*Source: Renze, "The Effect of Sampling Temperature on Problem Solving in Large Language Models" (arXiv:2402.05201, 2024)*

**What this means for agents:** For straightforward extraction, classification, and single-answer tasks, agonizing over `0.0` vs. `0.2` is unlikely to move your accuracy needle. Focus your tuning budget on prompt quality, structured output constraints, and tool design instead.

### The exception: multi-sample and test-time scaling

Where temperature *does* matter is when you generate **multiple reasoning traces** and select the best one (majority voting, best-of-N, or verifier-guided selection).

A 2025 NeurIPS study (arXiv:2510.02611) demonstrated that **different temperatures solve different subsets of problems**. Multi-temperature scaling yielded an additional **7.3 accuracy points** over single-temperature test-time scaling, averaged across Qwen3 models (0.6B–8B) on AIME 2024/2025, MATH500, LiveCodeBench, and Hi-ToM benchmarks. Base models with multi-temperature scaling reached performance **comparable to RL-trained counterparts** without any post-training.

*Source: "On the Role of Temperature Sampling in Test-Time Scaling" (arXiv:2510.02611, NeurIPS 2025)*

**Practical implication for multi-agent pipelines:**
- If you generate a single response per step → temperature choice is low-priority vs. prompt design.
- If you generate multiple candidates and select/vote → temperature diversity across samples is high-value.
- Entropy-based metrics can automatically identify near-optimal temperatures without task-specific validation data.

### Temperature matters most for tool calling reliability

While accuracy on standard benchmarks is temperature-insensitive, tool calling reliability tells a different story. Community testing on OpenAI's function calling API showed that **temperature 0 produces consistently correct tool arguments**, while higher temperatures (especially above 1.0) cause random, nonsensical parameter generation. This aligns with production experience: deterministic tool calls are critical for agent reliability.

*Source: OpenAI Developer Community testing, "Function Calling Temperature" (2025)*

### Bottom line: when to invest in temperature tuning

| Scenario | Temperature impact | Invest in tuning? |
| --- | --- | --- |
| Single-pass extraction/classification | Low (statistically insignificant) | No — focus on prompts |
| Tool calling / function invocation | High (reliability degrades above 0.3) | Yes — use 0.0–0.2 |
| Multi-sample + voting/selection | High (7+ point gains from diversity) | Yes — vary across samples |
| Reasoning model thinking mode | High (0.0 causes repetition loops) | Yes — follow provider defaults |
| Creative generation | Moderate (subjective quality) | Test with users |

---

## Part 1C — Adaptive Temperature (Research-Informed, Practical)

You don't have to keep temperature fixed. Recent research explores adaptive or learnable temperature / decoding policies, e.g.:

- **TAMPO (ICLR 2026)**: treats temperature as part of a meta-policy.
- **Dynamic temperature for code generation (arXiv 2023)**: proposes varying temperature during generation to improve results.
- **Adaptive Decoding via Latent Preference Optimization (arXiv 2024)**: adapts decoding to align with preferences.
- **Adaptive Temperature Scaling (EMNLP 2024)**: adjusts temperature based on uncertainty/signals to improve calibration and QA reliability.
- **Look Inward to Explore Outward (arXiv 2026)**: learns temperature from internal states via hierarchical RL.
- **Multi-temperature voting (NeurIPS 2025)**: reduces overhead of multi-temperature sampling while preserving gains.

Practical "good enough" approach (no fancy training required):

- **Exploration phase:** `temperature = 0.7–1.0` for 1–3 short bursts (ideas, hypotheses, search queries).
- **Exploitation phase:** `temperature = 0.0–0.3` for execution, tool use, and final assembly.

---

## Part 1D — Enforced Temperature Constraints (Provider-Specific)

Some providers enforce **exact temperature values** for certain models, rejecting any other value via API error. This is distinct from "recommended" temperatures — the API will return 400 Bad Request if the constraint is violated.

### Known enforced constraints

| Provider | Model | Mode | Enforced Temperature | Error on Violation |
|----------|-------|------|---------------------|--------------------|
| **Moonshot/Kimi** | `kimi-k2.5` | Instant (thinking disabled) | `0.6` (exact) | 400: `invalid temperature: only 0.6 is allowed for this model` |
| **Moonshot/Kimi** | `kimi-k2.5` | Thinking (thinking enabled) | `1.0` (exact) | 400: same pattern |
| **DeepSeek** | `deepseek-reasoner` | Always-think | Not accepted at all | Temperature parameter is ignored/rejected |

Other providers (OpenAI, Anthropic, Qwen, ZhipuAI) accept ranges and treat their documented values as recommendations, not hard constraints.

### Why this matters for multi-provider pipelines

In a multi-provider pipeline, agents typically set temperature based on their **task type** (e.g., `0.2` for deterministic extraction). When the orchestrator routes to a provider with enforced constraints, the agent's temperature is invalid.

**The fix must live in the provider layer**, not in agents or the orchestrator:

1. **Agents should not know about provider constraints** — they set temperature based on task requirements.
2. **The orchestrator should not hardcode per-model overrides** — it selects models, not sampling parameters.
3. **The provider method (`call_kimi`, `call_deepseek`, etc.) should enforce constraints** — it owns the API contract.

### Implementation pattern

Store enforced temperatures in the model registry as data:

```python
# In model registry
"kimi-k2.5": {
    "enforced_temperature": {"thinking": 1.0, "instant": 0.6},
    # ... other config
}
```

In the provider method, override before sending the API call:

```python
enforced = model_config.get("enforced_temperature")
if enforced:
    required = enforced["thinking" if thinking_mode else "instant"]
    if temperature is not None and temperature != required:
        logger.debug(f"Overriding temperature {temperature} → {required} for {model}")
    temperature = required
elif temperature is None:
    temperature = default_for_mode
```

This is data-driven: adding a new constrained model requires only a registry entry, not provider code changes.

### Checklist for new model integrations

When adding a new model to the registry, verify:

- [ ] Does the provider enforce exact temperature values? (Test with `temperature=0.0` and `temperature=0.5` — if one fails, it's enforced.)
- [ ] If enforced, add `enforced_temperature` to the registry entry.
- [ ] Does the provider reject temperature entirely for reasoning models? (Like `deepseek-reasoner`.)
- [ ] If rejected, omit temperature from the API kwargs for that model.

---

## Part 2 — Token Budgeting & Agent Economics

### Token budgeting terms (what to measure)

- **Input tokens:** prompt, tool schemas, retrieved context, conversation history.
- **Output tokens:** visible model output.
- **Hidden / reasoning tokens (provider-dependent):** some APIs count internal "reasoning" toward output limits; OpenAI's `max_output_tokens` explicitly covers visible output tokens and reasoning tokens in the Responses API.
- **Context window:** the maximum tokens a model can consider in a single request (provider/model specific).
- **Pricing:** providers often price input and output tokens differently; always use the provider's pricing page and treat output tokens as a budgeted resource.

### Why agents blow up budgets (root causes)

Agents often spend more tokens than single-turn chat because they repeatedly:

- re-send large system prompts and tool schemas
- inject tool results back into context
- loop (plan → act → observe) across multiple steps

Also note a key correction to a common misconception:

- **Billing is linear in tokens** (you pay per input/output token), even if model compute/latency can grow faster with longer contexts due to attention and infrastructure effects. Treat long contexts as expensive because they contain more tokens, not because billing is "exponential."

---

## Part 2A — The Real Cost of Agents (Evidence-Based)

Understanding the true cost structure is essential for designing effective budgets. The data below comes from production deployments documented in 2025–2026.

### Cost multipliers in production

| Cost Factor | Multiplier | Source |
| --- | --- | --- |
| **Agent vs. chatbot token use** | 3–10x more LLM calls per user request | Zylos Research, 2026 |
| **Output-to-input price ratio** | Median 4:1, up to 8:1 for reasoning models | Zylos Research, 2026 |
| **Multi-turn ReAct loop (10 cycles)** | ~50x tokens vs. single linear pass | Zylos Research, 2026 |
| **Unconstrained SWE agent task** | $5–8 per task in API fees | Zylos Research, 2026 |
| **Frontier vs. small model pricing** | Up to 190x cost spread | Zylos Research, 2026 |
| **POC → production cost scaling** | 50x–717x increase reported | Holter, "AI Costs in 2025" |

### The output token premium

Output tokens are **3–8x more expensive** than input tokens across nearly all providers. This is the single most important pricing asymmetry for agent architects. It creates strong incentives to:

1. **Use structured output schemas** (JSON mode, constrained decoding) to prevent verbose free-text.
2. **Avoid unnecessary chain-of-thought** when reasoning steps don't improve the final answer.
3. **Cap output tokens per step** — don't give a routing step 8,000 tokens when 200 suffice.

### Structured output reliability: use constrained decoding, not temperature

The JSONSchemaBench benchmark (2025) evaluated constrained decoding frameworks across 10,000 real-world JSON schemas and found that **constrained decoding** (Guidance, Outlines, XGrammar, OpenAI strict mode, Anthropic structured outputs) provides schema compliance **regardless of temperature**. Meanwhile, unconstrained generation with StructuredRAG showed an average JSON success rate of only 82.55% with high variance (0–100%). The StructEval benchmark found that even frontier models like o1-mini scored only 75.58% on structured output tasks without constraints.

**Takeaway:** Don't rely on low temperature to ensure valid JSON. Use your provider's constrained decoding feature (OpenAI `strict: true`, Anthropic `output_config.format`, etc.) and treat temperature as a secondary control.

*Sources: JSONSchemaBench (arXiv:2501.10868, 2025); StructEval (arXiv:2505.20139, 2025)*

---

## Part 2B — Hard Guardrails (Do This First)

### Provider-specific token budgets with thinking mode

When thinking is enabled, `max_tokens` means different things per provider. **This is the most dangerous semantic mismatch in multi-provider pipelines — the same `max_tokens=4000` produces radically different behavior depending on whether the provider counts thinking tokens against it.**

Last verified: **March 28, 2026** (from official provider documentation)

#### Full Provider Comparison Table

| Provider | Model | `max_tokens` Counts | Separate Thinking Budget? | Max Output Tokens | Max Thinking Budget | Context Window | Official Source |
|----------|-------|---------------------|--------------------------|-------------------|--------------------|-----------------|----|
| **Qwen/DashScope** | qwen3.5-plus | **Answer ONLY** | YES — `thinking_budget` param | 65,536 | 81,920 | 1,000,000 | *"max_tokens does not limit the length of the chain-of-thought"* — [DashScope API ref](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope) |
| **Qwen/DashScope** | qwen3.5-flash | **Answer ONLY** | YES — `thinking_budget` param | 65,536 | 81,920 | 1,000,000 | Same as above |
| **Qwen/DashScope** | qwen3.5-35b-a3b | **Answer ONLY** | YES — `thinking_budget` param | 65,536 | 81,920 | 262,144 | Same as above |
| **Qwen/DashScope** | qwen-plus | **Answer ONLY** | YES — `thinking_budget` param | 32,768 | 81,920 | ~1,000,000 | Same as above |
| **Qwen/DashScope** | qwen-flash | **Answer ONLY** | YES — `thinking_budget` param | 32,768 | 81,920 | ~1,000,000 | Same as above |
| **Qwen/DashScope** | qwen3-max | **Answer ONLY** | YES — `thinking_budget` param | 32,768 | 81,920 | 262,144 | Same as above |
| **DeepSeek** | deepseek-chat | **Answer ONLY** (never thinks) | N/A | 8,192 | N/A | 128,000 | [DeepSeek API ref](https://api-docs.deepseek.com/api/create-chat-completion) |
| **DeepSeek** | deepseek-reasoner | **Thinking + Answer COMBINED** | NO — no budget control at all | 65,536 (default 32K) | Uncontrollable | 128,000 | *"max_tokens: maximum output length (including the COT part)"* — [DeepSeek Reasoning Model](https://api-docs.deepseek.com/guides/reasoning_model) |
| **Kimi/Moonshot** | kimi-k2.5 (thinking ON) | **Thinking + Answer COMBINED** | NO — toggle only | 65,535 (default 32K) | No separate param | 262,144 | *"sum of tokens in reasoning_content and content ≤ max_tokens"* — [Kimi Thinking Models](https://platform.moonshot.ai/docs/guide/use-kimi-k2-thinking-model) |
| **Kimi/Moonshot** | kimi-k2.5 (thinking OFF) | **Answer ONLY** | N/A | 65,535 | N/A | 262,144 | Same as above |
| **Kimi/Moonshot** | kimi-k2 | **Answer ONLY** (never thinks) | N/A | Not documented | N/A | 262,144 | [Kimi API ref](https://platform.moonshot.ai/docs/api/chat) |
| **Kimi/Moonshot** | kimi-k2-thinking | **Thinking + Answer COMBINED** | NO — always-on thinking | Not documented | No separate param | 262,144 | Same as above |
| **ZhipuAI** | glm-5 | **Thinking + Answer COMBINED** (inferred) | NO — no separate param | 131,072 | No separate param | 200,000 | [Z.AI API ref](https://docs.z.ai/api-reference/llm/chat-completion); [Z.AI Core Params](https://docs.z.ai/guides/overview/concept-param) |
| **ZhipuAI** | glm-4.7 | **Thinking + Answer COMBINED** (inferred) | NO — no separate param | 131,072 | No separate param | 200,000 | Same as above |
| **ZhipuAI** | glm-4.7-flashx | **Thinking + Answer COMBINED** (inferred) | NO — no separate param | 131,072 | No separate param | 200,000 | Same as above |
| **ZhipuAI** | glm-4.7-flash | **Thinking + Answer COMBINED** (inferred) | NO — no separate param | 131,072 | No separate param | 200,000 | Same as above |

#### Summary by provider category

| Category | Providers | `max_tokens` Semantic | Thinking Budget Mechanism | Pipeline Implication |
|----------|-----------|----------------------|--------------------------|---------------------|
| **Separate budgets** | Qwen/DashScope (all models) | Answer ONLY | `thinking_budget` as independent `extra_body` param | `max_tokens` guarantees full answer space. Safest for structured JSON output |
| **Shared budget** | Kimi (thinking ON), ZhipuAI (thinking ON) | Thinking + Answer COMBINED | No separate param — must inflate `max_tokens` | `effective_max_tokens = max_tokens + thinking_budget`. Model decides the split; answer may be smaller than expected |
| **Shared budget, no control** | DeepSeek Reasoner | Thinking + Answer COMBINED | No budget control whatsoever | Model autonomously decides thinking/answer split. Cannot be influenced. Must inflate `max_tokens` to accommodate |
| **No thinking** | deepseek-chat, kimi-k2, kimi-k2.5 (OFF) | Answer ONLY | N/A | `max_tokens` = answer ceiling. No ambiguity |

#### Critical caveat: Self-hosted Qwen behaves DIFFERENTLY

The DashScope hosted API keeps `max_tokens` and `thinking_budget` as separate pools. Self-hosted Qwen (via HuggingFace transformers or vLLM) uses `max_new_tokens` as a **combined** ceiling for thinking + answer, and enforces `max_new_tokens > thinking_budget`. The remaining answer space = `max_new_tokens - reasoning_tokens_len`. **Do not assume DashScope semantics apply to self-hosted deployments.**

**Design pattern for multi-provider pipelines:** Set `max_tokens` based on answer-only estimates (matching Qwen semantics). In the model router, inflate `max_tokens` for providers without separate budgets: `effective_max_tokens = max_tokens + thinking_budget`.

### 1) Per-call caps

**OpenAI (Responses API)**

- Set `max_output_tokens` for every call.
- Set `max_tool_calls` to prevent tool-loop explosions.
- Consider `truncation = "disabled"` in development so over-context errors fail loudly; use `auto` only if you understand what content will be dropped.

**Anthropic**

- Set `max_tokens` for every call.
- Be aware that **rate limiting** can estimate output usage based on `max_tokens`; Anthropic's docs recommend lowering `max_tokens` if you hit output-token rate limits.
- **Token-efficient tool use:** Anthropic offers token-efficient tool calling that reduces overhead. Prompt cache read tokens no longer count against ITPM limits for newer models.

**Moonshot/Kimi**

- Set `max_tokens` (output token cap in their chat completion API).

**DeepSeek**

- Set `max_tokens` for every call. Context window varies by model (64K–128K).
- Monitor `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` in responses to measure caching effectiveness.
- For R1 reasoning models, account for reasoning tokens in your budget — they appear in the response and consume output tokens.

**Qwen (Alibaba Cloud)**

- Set `max_tokens` via DashScope or OpenAI-compatible interface.
- When using thinking mode (`enable_thinking: true`), budget for additional thinking tokens in the output.
- Use `result_format: "message"` in DashScope to get structured responses with usage data.

**GLM / Zhipu AI**

- Set `max_tokens` for every call. GLM-5 allows up to 128K output but default is conservative.
- When thinking mode is enabled, `reasoning_content` tokens count toward output — budget accordingly.
- Set `do_sample: false` for fully deterministic output when needed (stricter than `temperature = 0.0` with sampling on).

### 2) Per-request "global" budget in the orchestrator

Implement budgets above the API layer:

- `max_total_input_tokens`
- `max_total_output_tokens`
- `max_total_tool_calls`
- `max_steps` / `max_iterations`
- `max_wall_clock_seconds`

Stop early with a partial result when budgets are exceeded ("Here's what I found so far…") instead of timing out unpredictably.

### 3) Multi-level rate limiting (production pattern)

Production systems should implement hierarchical guardrails at four levels (source: Athenic AI, "AI Agent Rate Limiting"):

| Level | What it controls | Why |
| --- | --- | --- |
| **Per-request** | Max input/output tokens, tool calls, execution time | Prevent single-call blowups |
| **Per-user** | Token/request caps per time window | Prevent individual abuse |
| **Per-organization** | Aggregate budget across users | Business cost control |
| **Global** | System-wide circuit breaker | Catch cascading failures |

**Key insight:** Prioritize token-based limits over request counts — a single 100K-token request costs 100x more than a 1K-token request. Pre-flight estimation that catches expensive requests *before* execution enables graceful degradation (smaller models, shorter outputs) rather than hard rejections.

### 4) Track and enforce using usage fields

Use provider usage fields to measure reality, not guesses. OpenAI's Responses API returns usage (input/output tokens and output token details such as reasoning tokens). Anthropic provides a dedicated token counting endpoint and also returns usage in responses depending on API route/model.

---

## Part 2C — Prompt Caching (Biggest ROI Optimization)

Prompt caching is consistently the **highest single-impact optimization** for agent workloads.

### Production impact (measured)

| Provider | Mechanism | Cost Savings | Latency Reduction | Source |
| --- | --- | --- | --- | --- |
| **Anthropic** | Explicit `cache_control` markers | ~90% on cached tokens ($0.30/M vs $3.00/M) | 75–85% | Anthropic docs; Zylos 2026 |
| **OpenAI** | Automatic prefix caching | ~50% on repeated prefixes | Significant (model-dependent) | OpenAI docs |
| **DeepSeek** | Automatic disk-based prefix caching | ~90% ($0.014/M vs $0.14/M) | 13s → 500ms (128K prompt) | DeepSeek docs |

### OpenAI prompt caching (Responses API)

OpenAI provides a prompt caching guide describing automatic caching for repeated prefixes (e.g., long system prompts and static context) and states that caching can reduce latency and reduce the cost of cached **input tokens** substantially (model dependent). The Responses API also exposes `prompt_cache_key` and `prompt_cache_retention` options.

**Design rule:** put your *static* prefix first, and push dynamic/user-specific content later. If the prefix changes, you get a cache miss.

### Anthropic prompt caching (`cache_control`)

Anthropic's prompt caching docs describe:

- cache lifetime (e.g., 5 minutes by default; optional longer TTL)
- cache breakpoints (up to 4 per request)
- ordering guidance (tools → system → messages) to maximize shared prefixes
- **Cache-aware rate limits:** Prompt cache read tokens no longer count against ITPM limits on newer models, further incentivizing caching.
- **Simplified caching:** Claude automatically reads from the longest previously cached prefix, eliminating manual segment tracking.

**Design rule:** treat cached blocks like "compiled headers": keep them stable and early.

### DeepSeek context caching (automatic, disk-based)

DeepSeek's caching is automatic and prefix-based (no code changes needed):

- Only requests with **identical prefixes from token 0** trigger cache hits; partial matches don't count.
- Cache hit tokens are priced at ~90% discount (≈$0.014/M tokens vs $0.14/M for misses).
- API responses include `prompt_cache_hit_tokens` and `prompt_cache_miss_tokens` for monitoring.
- For a 128K prompt with high prefix reuse, first-token latency dropped from 13s to 500ms.

**Design rule:** identical to OpenAI/Anthropic — put static content (system prompt, docs, schemas) first; push dynamic content (user query, timestamps) last.

### Qwen and GLM caching

- **Qwen:** when accessed via the OpenAI-compatible interface, Qwen benefits from Alibaba Cloud's server-side caching. DashScope native API may offer additional caching controls.
- **GLM (Zhipu AI):** GLM-5 documentation references context caching for optimized long conversations; the design principle is the same: stable prefixes first.

### Semantic caching (application-level)

Beyond provider prefix caching, **semantic caching** catches queries that are semantically equivalent but not identical. Research shows ~31% of LLM queries across typical workloads exhibit semantic similarity — a large share of API calls that can be eliminated entirely (100% cost savings on cache hits, millisecond response times).

Tools: GPTCache, Redis with vector search, ScyllaDB.

**Caution:** Security research has identified key-collision attacks where adversarially crafted queries can poison caches; production deployments need similarity threshold auditing.

---

## Part 2D — Model Routing & Output Shaping

### Route work to the cheapest model that can do it

Token budgeting is easier when you avoid spending premium-model tokens on cheap work:

- Use smaller/faster models for extraction, routing, formatting, and short summaries.
- Use frontier/reasoning models only for steps that truly need them (planning, hard coding, high-stakes decisions).

**Evidence from production:** Model routing cascades achieve **87% cost reduction** by ensuring expensive frontier models handle only the ~10% of queries genuinely requiring their capabilities (Zylos Research, 2026). OpenAI's GPT-5 architecture explicitly routes between an efficient fast model and a deeper reasoning model based on query complexity.

### How vertical platforms handle routing

| Platform / Category | Approach | Source |
| --- | --- | --- |
| **Cursor (coding IDE)** | 200K token context window; routes between fast models (tab completion) and frontier models (agent tasks); always-apply rules consume tokens per prompt, so glob-scoped rules preferred | Cursor docs, 2025 |
| **Cognition/Devin (SWE agent)** | Specialized subagents: SWE-grep (RL-trained) for fast context retrieval (matching frontier quality at 10x less time), frontier models for reasoning; 60%+ of first-turn tokens were wasted on context retrieval before optimization | Cognition blog, 2025 |
| **Devin pricing model** | Uses Agent Compute Units (ACUs) at ~$2.00–2.25/ACU as abstracted billing metric instead of raw token pricing; 67% PR merge rate after architecture optimizations | Cognition, Lindy AI, 2025–2026 |
| **Perplexity (AI search)** | Search mode (real-time web RAG) vs. no-search mode; multi-query decomposition (up to 5 sub-queries); avoids few-shot examples that confuse web search; constrained citation scoping for factual grounding | Perplexity docs, 2025 |
| **GitHub Copilot (coding)** | MCP-based tool calling; task scoping guidance (simpler tasks preferred); environment-aware via CI/CD; read-only tool allowlisting for autonomous operation | GitHub docs, 2025 |

### Shape outputs to reduce token burn

High-impact tactics:

- Prefer **tool calls** or **schemas** for agent-to-agent messages.
- Instruct for **concise** outputs (lists, short rationales) during intermediate steps.
- Cap verbosity explicitly (e.g., "Max 6 bullets", "Output JSON only").
- **Use constrained decoding** (OpenAI `strict: true`, Anthropic structured outputs) rather than hoping low temperature will prevent schema violations.

Avoid paying for filler:

- "Sure, here is the JSON you requested…"
- long self-explanations when you only need structured state

---

## Part 2E — Advanced Token Optimization (Research-Backed)

### Adaptive token allocation: SelfBudgeter

SelfBudgeter (Peking University / ByteDance, 2025; arXiv:2505.11274) enables models to **self-estimate required reasoning budgets** based on query complexity. Results:

- **61% response length compression** (1.5B model) and **48% compression** (7B model) on math benchmarks while maintaining accuracy.
- Up to **74.47% compression** on MATH benchmark.
- Users can see anticipated generation time and control token budgets upfront.

**Practical relevance:** Even without fine-tuning, you can approximate this pattern by instructing your agent to estimate task difficulty before allocating tokens ("Classify this as easy/medium/hard, then respond accordingly").

### Multi-agent communication pruning: AgentPrune

AgentPrune (ICLR 2025; arXiv:2410.02506) identifies and removes redundant inter-agent messages through spatial-temporal graph pruning:

- **28.1%–72.8% token reduction** across benchmarks.
- **8x cost savings** ($5.6 vs $43.7) while maintaining accuracy.
- One-shot pruning — no iterative retraining needed.
- Bonus: defends against agent-based adversarial attacks with 3.5%–10.8% performance improvement.

**Practical relevance:** In multi-agent pipelines, audit whether every inter-agent message is necessary. Pruning redundant handoff context is often the cheapest optimization.

### Runtime supervision: SupervisorAgent

SupervisorAgent (arXiv:2510.26585, 2025) reduces token consumption by **29.45%** through lightweight runtime interventions:

- Operates **without altering base agent architecture** — modular plugin.
- Uses an **LLM-free adaptive filter** to detect high-risk scenarios (errors, excessively long observations, inefficient patterns) and intervene only at critical moments.
- Supervises three interaction points: agent-agent, agent-tool, agent-memory.

**Practical relevance:** Add lightweight heuristic checks between agent steps (output length thresholds, error detection, loop detection) before adding another LLM call.

### Budget-aware test-time scaling: BATS

BATS (Budget Aware Test-time Scaling, 2025) provides agents with **continuous budget awareness** through a lightweight plugin:

- Agents dynamically adapt strategies — "dig deeper" on promising leads or "pivot" to new paths based on remaining resources.
- Uses a **unified cost metric** jointly accounting for token and tool consumption.
- Addresses the finding that agents lacking budget awareness hit performance ceilings quickly when given larger budgets.

**Practical relevance:** Expose remaining budget to your agent in the system prompt or tool results. Agents that know their budget make better allocation decisions.

### Prompt compression: LLMLingua

LLMLingua and similar techniques use a small, fast language model to identify and remove low-information tokens from long prompts:

- Typical compression: **95% input cost reduction** (800 tokens → 40 tokens) on verbose prompts.
- Compression ratios up to **20x** with acceptable quality degradation for summarization and Q&A.

**Practical relevance:** For RAG pipelines, extractive summarization of retrieved chunks before injection is a practical alternative.

### Compound savings

The Zylos Research report (2026) notes that combining prompt compression + model routing + caching delivers **60–80% total cost reduction** without meaningful quality degradation for most production workloads.

---

## Part 2F — Context Management (Agents Need a Lifecycle)

Avoid "ever-growing transcripts." Instead:

- **Summarize with intent:** keep decisions, constraints, and open questions; discard raw tool logs.
- **Chunk + retrieve:** don't shove entire documents into context; retrieve the minimum relevant parts.
- **Truncate tool outputs:** logs, HTML, and stack traces can dominate input tokens.
- **Use structured intermediate state:** JSON state objects are cheaper than verbose prose and easier to validate.
- **Context lifecycle rules:** Distinguish ephemeral interaction (discard after step), working memory (retain for pipeline), and durable state (persist to database). Cognition/Devin found that agents spent 60%+ of first-turn tokens on context retrieval — purpose-built retrieval models (SWE-grep) solved this at 10x less cost.

Anthropic's context window docs also note that some internal blocks (like thinking blocks) are stripped from history, which can matter for budgeting and long-running threads.

### Batch APIs for async workloads

Both OpenAI and Anthropic offer **50% discounts** on batch APIs for non-real-time workloads. Agents with separable planning and execution phases can defer planning to batch, keeping only real-time user interactions on standard inference.

---

## Part 2G — FinOps: Cost Observability

Without granular cost attribution, optimization is guesswork. Track these metrics:

| Metric | Why It Matters |
| --- | --- |
| **Cost per trace / workflow run** | Identify expensive agent workflows |
| **Cost per user** | Detect power users driving disproportionate spend |
| **Cost per model tier** | Validate routing decisions are working |
| **Cache hit rate** | Measure return on caching investment |
| **Tokens per tool call** | Identify tool schemas bloating context |
| **Output token ratio** | Catch verbose intermediate reasoning runaway |

**Tooling ecosystem (2026):**
- **Langfuse / Traceloop:** Open-source LLM tracing with cost attribution at the trace/span level.
- **Portkey / Helicone:** LLM gateway proxies with per-request cost tracking, budget limits, and usage breakdowns.
- **Datadog LLM Observability:** Enterprise-grade cost monitoring integrated with cloud cost management.

**Budget controls for production:**
- Spend anomaly alerts (flag >2σ deviation from baseline)
- Token budget per trace (reject or truncate requests exceeding ceiling)
- Max iterations cap in orchestration framework
- Pre-flight cost estimation for graceful degradation

*Source: Zylos Research, "AI Agent Cost Optimization: Token Economics and FinOps in Production" (2026)*

---

## Good Examples (Copyable Patterns)

### Good example 1: Deterministic tool call with tight budgets (OpenAI-style)

```json
{
  "model": "YOUR_MODEL",
  "temperature": 0,
  "top_p": 1,
  "max_output_tokens": 400,
  "max_tool_calls": 3,
  "truncation": "disabled",
  "seed": 1234,
  "input": [
    { "role": "system", "content": "You are a tool-using agent. Output must match the schema." },
    { "role": "user", "content": "Extract fields from this text: ..." }
  ]
}
```

Why it's good:

- Low variance for tool selection and schemas.
- Explicit caps prevent tool loops and runaway outputs.
- Seed helps reproducibility in tests (best-effort).

### Good example 2: Hot generator + cold judge (provider-agnostic)

1) Generate 5 options at higher temperature (`0.8–1.0`).  
2) Judge and pick at low temperature (`0.0–0.2`) with a rubric.  
3) Final rewrite at low/medium temperature (`0.2–0.4`) for coherence.

This gets diversity *and* stability. Multi-temperature sampling across candidates yields an additional ~7 accuracy points on reasoning tasks (NeurIPS 2025).

### Good example 3: Cache-friendly agent prefix (Anthropic-style)

Place stable content (tools, long system spec, fixed background docs) in a cached block, and keep user input after it. With Anthropic's simplified caching, Claude automatically reads from the longest previously cached prefix — no manual segment tracking needed.

### Good example 4: Right-size output caps (Anthropic-style)

If your step only needs a short answer, don't give it a huge cap. This reduces cost and can also reduce rate-limit pressure.

```json
{
  "model": "YOUR_MODEL",
  "temperature": 0.2,
  "max_tokens": 600,
  "messages": [
    { "role": "user", "content": "Classify this ticket into one label from: A, B, C. Ticket: ..." }
  ]
}
```

### Good example 5: Moonshot/Kimi defaults (Moonshot-style)

Moonshot's older models accept `temperature` in range `0–1`, but **Kimi K2.5 enforces exact values**: `0.6` (instant) and `1.0` (thinking). Your provider layer must override any caller-specified temperature for K2.5.

```json
{
  "model": "kimi-k2.5",
  "temperature": 0.6,
  "top_p": 0.95,
  "max_tokens": 2000,
  "extra_body": { "thinking": { "type": "disabled" } },
  "messages": [
    { "role": "user", "content": "Summarize this in 5 bullets: ..." }
  ]
}
```

### Good example 6: DeepSeek coding with caching (DeepSeek-style)

DeepSeek recommends `temperature: 0.0` for coding. Pair with their automatic prefix caching for multi-turn code sessions.

```json
{
  "model": "deepseek-coder",
  "temperature": 0.0,
  "max_tokens": 4096,
  "messages": [
    { "role": "system", "content": "You are a senior Python developer. Output only valid code." },
    { "role": "user", "content": "Refactor this function to use async/await: ..." }
  ]
}
```

Why it's good:

- Deterministic output for code.
- System prompt stays stable across turns, triggering DeepSeek's automatic disk cache.
- Right-sized `max_tokens` for a code refactor.

### Good example 7: Qwen3 with thinking mode (Qwen-style)

Qwen3's thinking mode needs `temperature > 0` — greedy decoding breaks it.

```json
{
  "model": "qwen3-max",
  "temperature": 0.6,
  "top_p": 0.95,
  "max_tokens": 8192,
  "enable_thinking": true,
  "messages": [
    { "role": "user", "content": "Design a database schema for a multi-tenant SaaS app with RLS." }
  ]
}
```

Why it's good:

- `temperature = 0.6` follows Qwen3's recommendation for thinking mode (avoids repetition loops at 0.0).
- Thinking enabled for a complex reasoning task.
- `max_tokens` is generous enough for reasoning + final answer.

### Good example 8: GLM-5 with thinking and controlled sampling (GLM-style)

```json
{
  "model": "glm-5",
  "temperature": 1.0,
  "top_p": 0.95,
  "max_tokens": 4096,
  "thinking": { "type": "enabled" },
  "messages": [
    { "role": "user", "content": "Analyze the security implications of this API design: ..." }
  ]
}
```

Why it's good:

- Default temperature/top_p (GLM-5 defaults: 1.0/0.95) for a reasoning task.
- Thinking mode enabled for deep analysis.
- Moderate `max_tokens` for structured output.

### Good example 9: Budget-aware agent with remaining-budget exposure

```python
# Expose remaining budget to the agent so it can self-regulate
remaining_budget = total_budget - tokens_used_so_far
system_prompt = f"""You are a research agent.
Remaining token budget: {remaining_budget} tokens.
Remaining tool calls: {max_tool_calls - calls_used}.
If budget is low, summarize findings and stop. Do not start new exploration."""
```

Why it's good:

- Budget-aware agents make better allocation decisions (BATS, 2025).
- Prevents stuck loops from consuming uncapped resources.
- Graceful degradation with partial results instead of hard failures.

### Good example 10: Tiered model routing per agent step

```python
# Route each pipeline step to the cheapest adequate model
STEP_MODEL_MAP = {
    "spec_parsing":      "fast-model",       # Extraction — cheap model suffices
    "planning":          "frontier-model",    # Complex reasoning — needs frontier
    "criteria_gen":      "mid-tier-model",    # Moderate complexity
    "review":            "frontier-model",    # Quality-critical
    "description_polish": "mid-tier-model",   # Writing — mid-tier handles well
}
```

Why it's good:

- Matches model capability to task complexity (87% cost reduction potential).
- Easy to tune — promote/demote individual steps based on quality metrics.
- Avoids paying frontier prices for tasks a smaller model handles equally well.

---

## Bad Examples (Anti-Patterns to Avoid)

### Bad example 1: "High temperature JSON extraction"

```json
{ "temperature": 1.0, "max_output_tokens": 4000, "input": "Return JSON..." }
```

Why it's bad:

- High temperature increases the chance of invalid JSON and schema drift.
- Oversized output caps inflate cost and amplify failure modes.
- **Fix:** Use `temperature = 0.0–0.2` AND constrained decoding (`strict: true` or structured outputs).

### Bad example 2: "No caps in an agent loop"

- No `max_output_tokens` / `max_tokens`
- No tool call limit
- No max iterations

Why it's bad:

- One edge case (tool error, ambiguous user input, retry loop) can explode token spend.
- Production data shows 50x–717x cost scaling from uncontrolled loops.

### Bad example 3: "Caching turned on, but dynamic content first"

If you put user-specific or timestamped content at the start of the prompt, you break prefix caching and lose most of the benefit.

### Bad example 4: "Max tokens set to the sky for every call"

Example:

- Set `max_output_tokens = 8000` / `max_tokens = 8000` for simple routing/extraction steps.

Why it's bad:

- You pay more when the model rambles.
- It can increase retry/loop damage.
- Some providers use `max_tokens` to estimate rate limit usage; oversized caps can cause throttling earlier than necessary.

### Bad example 5: "Greedy decoding with thinking/reasoning mode"

```json
{ "model": "qwen3-max", "temperature": 0.0, "enable_thinking": true }
```

Why it's bad:

- Qwen3, DeepSeek-R1, and GLM-5 thinking modes require `temperature > 0` for the reasoning phase to explore properly.
- `temperature = 0.0` with thinking mode causes performance degradation and can trigger endless repetition loops (documented by Qwen).
- Fix: use the model's recommended thinking-mode temperature (e.g., Qwen3: `0.6`, DeepSeek R1: `1.0` for reasoning tasks).

### Bad example 6: "json_object + thinking mode"

```python
result = await llm.call(
    prompt=prompt,
    model="qwen3-max",
    response_format="json_object",
    enable_thinking=True,
    thinking_budget=4096,
)
```

Why it's bad:

- `response_format="json_object"` is incompatible with thinking mode on all Chinese LLM providers (Qwen, Kimi, ZhipuAI).
- Some providers put JSON in `reasoning_content` instead of `content`; others produce invalid output or API errors.
- The `thinking_budget` and `enable_thinking` params become dead code — thinking is silently suppressed.
- Fix: drop `json_object`, prompt-instruct JSON output, add `_extract_json_from_text()` fallback with retry. Thinking is the core capability; JSON format is a convenience replicable via prompting.

### Bad example 7: "Agent-chosen temperature sent to enforced-temperature model"

```python
# Agent sets temperature for its task type
class RoleAgent(BasePipelineAgent):
    def __init__(self):
        super().__init__(temperature=0.2, ...)  # Deterministic extraction

# Provider passes it through unchecked
kwargs = {"model": "kimi-k2.5", "temperature": 0.2, ...}
# → 400 Bad Request: "invalid temperature: only 0.6 is allowed for this model"
```

Why it's bad:

- Kimi K2.5 enforces `temperature=0.6` (instant) / `1.0` (thinking). Any other value is a hard API error.
- The agent's `0.2` is correct for its task (deterministic extraction) but invalid for this specific model.
- Silent fallback to another provider means Kimi K2.5 is never actually used, wasting the model selection logic.
- Fix: The provider method must check for `enforced_temperature` in the model registry and override before sending the API call. Agents should remain model-agnostic.

### Bad example 8: "Frontier model for every step"

```python
# Every step uses the most expensive model
for step in pipeline:
    result = call_llm(model="gpt-5-reasoning", step=step)
```

Why it's bad:

- Frontier reasoning models cost up to 190x more than fast alternatives.
- Extraction, formatting, and routing steps rarely benefit from frontier models.
- Fix: Use tiered model routing (see Good example 10).

### Bad example 9: "Independent sibling fetches"

```python
# Three agents independently fetch the same context
agent_1_context = fetch_full_document()  # 50K tokens
agent_2_context = fetch_full_document()  # 50K tokens (duplicate)
agent_3_context = fetch_full_document()  # 50K tokens (duplicate)
```

Why it's bad:

- 150K tokens when 50K would suffice with shared context.
- Also triggers rate limiting from burst requests.
- Fix: Fetch once at the orchestrator level, pass as shared state.

---

## Checklist (Before Shipping an Agent)

### Temperature
- [ ] Every call sets `temperature` deliberately (not default-by-accident).
- [ ] You tune either `temperature` **or** `top_p` (not both) unless you have measured a benefit.
- [ ] If using thinking/reasoning mode (Qwen3, DeepSeek R1, GLM-5, Anthropic extended thinking), temperature is set above 0 and thinking token budget is accounted for.
- [ ] Tool-calling steps use `temperature = 0.0–0.2` for reliable argument generation.
- [ ] If using multi-sample generation, temperatures are varied across samples for diversity.
- [ ] Provider layer enforces model-specific temperature constraints (e.g., Kimi K2.5 accepts only `0.6`/`1.0`). Agent-specified temperatures are overridden transparently, not passed through unchecked.

### Token Budgets
- [ ] Every call sets `max_output_tokens` / `max_tokens`, plus tool/step caps.
- [ ] Orchestrator enforces per-request total budget (input + output + tool calls + iterations + wall clock).
- [ ] Output token caps are right-sized per step (routing: ~200, extraction: ~500, planning: ~2000).
- [ ] Budget-remaining information is exposed to agents where applicable.
- [ ] If thinking mode is enabled, `response_format="json_object"` is NOT used (incompatible on Chinese LLM providers — use prompt-instruct JSON + extraction fallbacks instead).
- [ ] Provider-specific `max_tokens` semantics are handled: answer-only for Qwen (separate `thinking_budget`), combined for Kimi/ZhipuAI (inflate by `thinking_budget`), combined for DeepSeek Reasoner (must also inflate — no separate budget control). See "Full Provider Comparison Table" in Part 1.

### Caching
- [ ] Prompt caching is designed-in (stable prefix first, dynamic content last).
- [ ] Cache hit rates are monitored and maintained above target.
- [ ] Semantic caching is evaluated for frequently repeated queries.

### Model Routing
- [ ] Each pipeline step uses the cheapest model that meets its quality bar.
- [ ] Model routing decisions are logged and periodically audited.

### Cost Observability
- [ ] Usage is logged per trace/step with provider usage fields.
- [ ] Budget circuit breakers are in place (anomaly alerts, per-trace caps).
- [ ] Cost trends are reviewed regularly.

### Context Management
- [ ] Context has a lifecycle (summaries, retrieval, truncation of tool outputs).
- [ ] Shared context is fetched once at orchestrator level, not duplicated by siblings.
- [ ] Structured intermediate state (JSON) is used over verbose prose.

---

## References (Authoritative + Research)

### Provider Documentation

**OpenAI**

- Responses API (create): https://platform.openai.com/docs/api-reference/responses/create
- Reproducible outputs (seed/system_fingerprint): https://platform.openai.com/docs/guides/production-best-practices/reproducible-outputs
- Prompt caching: https://platform.openai.com/docs/guides/prompt-caching
- Structured outputs: https://developers.openai.com/api/docs/guides/structured-outputs
- Function calling: https://platform.openai.com/docs/guides/function-calling
- Tokens guide: https://platform.openai.com/docs/guides/tokens
- Agents SDK ModelSettings: https://openai.github.io/openai-agents-python/ref/model_settings/
- A Practical Guide to Building Agents: https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf
- Pricing: https://openai.com/pricing

**Anthropic**

- Building Effective Agents: https://anthropic.com/research/building-effective-agents
- Token-saving updates: https://anthropic.com/news/token-saving-updates
- Token-efficient tool use: https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/token-efficient-tool-use
- Structured outputs: https://docs.anthropic.com/en/docs/build-with-claude/structured-outputs
- Prompt caching: https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching
- Context windows: https://docs.anthropic.com/en/docs/build-with-claude/context-windows
- Extended thinking: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking
- Extended thinking tips: https://docs.anthropic.com/en/docs/build-with-claude/extended-thinking-tips
- Rate limits: https://docs.anthropic.com/en/api/rate-limits
- Count tokens endpoint: https://docs.anthropic.com/en/api/count-tokens
- Pricing: https://www.anthropic.com/pricing

**Moonshot / Kimi**

- Moonshot API reference: https://platform.moonshot.cn/api.html
- Moonshot platform docs: https://platform.moonshot.ai/docs/api/chat
- Kimi-K2 repository: https://github.com/MoonshotAI/Kimi-K2
- Kimi-K2.5 repository: https://github.com/MoonshotAI/Kimi-K2.5
- Kimi-K2.5 quickstart: https://platform.moonshot.cn/docs/guide/kimi-k2-5-quickstart

**DeepSeek**

- Temperature parameter guide: https://api-docs.deepseek.com/quick_start/parameter_settings/
- Chat Completion API: https://api-docs.deepseek.com/api/create-chat-completion
- Context Caching on Disk: https://api-docs.deepseek.com/guides/kv_cache
- Context Caching announcement: https://api-docs.deepseek.com/news/news0802
- Models & Pricing: https://api-docs.deepseek.com/quick_start/pricing/
- DeepSeek-R1: https://github.com/deepseek-ai/DeepSeek-R1

**Qwen (Alibaba Cloud)**

- Qwen API (DashScope native): https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope
- Qwen API (OpenAI-compatible): https://www.alibabacloud.com/help/en/model-studio/developer-reference/use-qwen-by-calling-api
- Qwen API (OpenAI Responses API): https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-responses
- Qwen3 quickstart: https://qwen.readthedocs.io/en/v3.0/getting_started/quickstart.html
- Qwen3 GitHub: https://github.com/QwenLM/Qwen3
- Qwen-Agent configuration: https://qwenlm.github.io/Qwen-Agent/en/guide/get_started/configuration/

**GLM / Zhipu AI**

- GLM-5 model overview: https://docs.z.ai/guides/llm/glm-5
- Core parameters: https://docs.z.ai/guides/overview/concept-param
- Migration to GLM-5: https://docs.z.ai/guides/overview/migrate-to-glm-new
- Chat Completion API: https://zhipu-32152247.mintlify.app/api-reference/llm/chat-completion

**Google (Vertex AI / Gemini)**

- Adjust parameter values: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/prompts/adjust-parameter-values
- Grounding with Google Search: https://docs.cloud.google.com/vertex-ai/generative-ai/docs/grounding/grounding-with-google-search
- Prompt best practices: https://cloud.google.com/vertex-ai/generative-ai/docs/learn/prompt-best-practices

**Perplexity**

- Search best practices: https://docs.perplexity.ai/docs/search/best-practices
- Prompt guide: https://docs.perplexity.ai/docs/grounded-llm/prompting/prompt-guide

### Vertical Platform & Industry References

- Cursor token management: https://developertoolkit.ai/en/cursor-ide/advanced-techniques/token-management/
- Cognition/Devin SWE-grep: https://cognition.ai/blog/swe-grep
- Cognition/Devin 2025 performance review: https://cognition.ai/blog/devin-annual-performance-review-2025
- GitHub Copilot coding agent best practices: https://docs.github.com/en/copilot/how-tos/agents/copilot-coding-agent/best-practices-for-using-copilot-to-work-on-tasks
- AI Agent Rate Limiting (Athenic): https://getathenic.com/blog/ai-agent-rate-limiting-token-budgets
- Building Vertical AI playbook (Bessemer): https://www.bvp.com/atlas/building-vertical-ai-an-early-stage-playbook-for-founders

### Production Cost & FinOps

- Zylos Research, "AI Agent Cost Optimization: Token Economics and FinOps in Production" (Feb 2026): https://zylos.ai/research/2026-02-19-ai-agent-cost-optimization-token-economics
- Holter, "AI Costs in 2025: Cheaper Tokens, Pricier Workflows" (2025): https://adam.holter.com/ai-costs-in-2025-cheaper-tokens-pricier-workflows-why-your-bill-is-still-rising/
- Budget-Aware Tool-Use Enables Effective Agent Scaling (BATS): https://arxiv.org/html/2511.17006v1
- Beyond Accuracy: Multi-Dimensional Framework for Enterprise Agentic AI (2025): https://arxiv.org/html/2511.14136v1

### Research Papers

**Temperature**

- Renze (2024), "The Effect of Sampling Temperature on Problem Solving in LLMs": https://arxiv.org/abs/2402.05201 / https://github.com/matthewrenze/jhu-llm-temperature
- "On the Role of Temperature Sampling in Test-Time Scaling" (NeurIPS 2025): https://arxiv.org/abs/2510.02611
- Du et al. (2025), "Optimizing Temperature for Language Models with Multi-Sample Inference" (ICML): https://proceedings.mlr.press/v267/du25f.html
- Holtzman et al. (2019), nucleus sampling: https://arxiv.org/abs/1904.09751
- Dhuliawala et al. (2024), Adaptive Decoding via Latent Preference Optimization: https://arxiv.org/abs/2411.09661
- Zhu et al. (2023), "Hot or Cold?" Adaptive Temperature for Code Generation: https://arxiv.org/abs/2309.02772
- Xie et al. (EMNLP 2024), Calibrating Language Models with Adaptive Temperature Scaling: https://arxiv.org/abs/2409.19817
  - Code: https://github.com/Johnathan-Xie/adaptive-temperature-scaling
- Dang et al. (ICLR 2026), TAMPO — Temperature as a Meta-Policy: https://arxiv.org/abs/2602.11779
  - OpenReview: https://openreview.net/forum?id=AoTHU2OmS6
- Dang et al. (2026), Look Inward to Explore Outward — Learning Temperature via Hierarchical RL: https://arxiv.org/abs/2602.13035

**Token Budgeting & Multi-Agent Optimization**

- SelfBudgeter (2025), Adaptive Token Allocation for Efficient LLM Reasoning: https://arxiv.org/abs/2505.11274
- AgentPrune (ICLR 2025), Cut the Crap — Economical Communication Pipeline for LLM Multi-Agent Systems: https://arxiv.org/abs/2410.02506 / https://github.com/yanweiyue/AgentPrune
- SupervisorAgent (2025), Stop Wasting Your Tokens — Efficient Runtime Multi-Agent Systems: https://arxiv.org/abs/2510.26585
- BATS (2025), Cost-effective Agent Test-time Scaling via Budget-Aware Thinking: https://openreview.net/forum?id=AaMB3SFmBy

**Structured Output**

- JSONSchemaBench (2025), Rigorous Benchmark of Structured Outputs for Language Models: https://arxiv.org/abs/2501.10868
- StructEval (2025), Benchmarking LLMs' Capabilities to Generate Structural Outputs: https://arxiv.org/abs/2505.20139

**Guardrails & Safety**

- LlamaFirewall (2025), Open Source Guardrail System for Secure AI Agents: https://arxiv.org/abs/2505.03574
