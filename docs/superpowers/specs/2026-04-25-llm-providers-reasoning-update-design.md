# LLM Providers — Reasoning Models Update Design

**Date:** 2026-04-25
**Status:** Draft for review
**Touches:** `server/board/llm.py`, `server/board/config.py`, `server/board/metrics.py`, `docs/LLM_PROVIDERS_GUIDEBOOK.md`
**Author:** Brainstormed with the operator on 2026-04-25.

## 1 — Goal

Bring the LLM layer in line with the April 2026 reasoning-model landscape captured in `docs/LLM_PROVIDERS_GUIDEBOOK.md`:

1. **Integrate the new models** so that handler-level quirks (DeepSeek `reasoning_effort`, Gemini `thinking_budget`/`thinking_level`, Kimi K2.6 constraints, Qwen 3.6 `preserve_thinking`) work without manual workarounds.
2. **Default the board to reasoning** by switching `CHAIRMAN_MODEL`, `COUNCIL_MODELS`, and `VERIFICATION_MODEL` to the latest per-provider reasoning model. Keep `CLASSIFIER_MODEL` on a fast non-reasoner (gemini free tier).
3. **Right-size the call defaults** for reasoning workloads (`max_tokens` 4096 → 8192, `timeout` 120 → 240; `temperature` stays 0.7).
4. **Document the new Qwen 3.6 family** in the guidebook so operators can pick it confidently.

Out of scope: deliberation pipeline changes, member `.md` edits, ReasoningProfile abstraction, capturing `reasoning_content` for UI display.

## 2 — Why these specific defaults

### Chairperson: `kimi/kimi-k2.6`

Latest Moonshot flagship, released 2026-04-20. Replaces the current `kimi/kimi-k2.5` default; same provider so the verifier-decoupling check still passes. Thinking is on by default; the K2.5 temperature/top_p/n constraints carry over and are already enforced in the handler.

### Council: 3 distinct families, no kimi overlap

```python
DEFAULT_COUNCIL_MODELS = [
    "deepseek/deepseek-v4-pro",
    "glm/glm-5.1",
    "qwen/qwen3.6-max-preview",
]
```

The orchestrator uses `models[i % len(models)]` round-robin — adding more entries does NOT multiply per-call cost, it widens the perspective pool. Three families gives every council member a reasoning model from a different provider than the chairperson (kimi), so peer review in Stage 2 isn't echoing the chair's family bias.

Kimi is intentionally NOT in the council list because the chairperson already runs on it.

### Classifier: `gemini/gemini-2.5-flash`

Per operator: "use gemini free tier for other goals, not for reasoning." Classification is exactly that — short, structured, no deep reasoning required. Free tier rate limits (5–15 RPM) are well within a single deliberation's usage profile.

### Verifier: `deepseek/deepseek-v4-pro`

Must be a different provider than the chairperson (kimi). Three reasoning-capable candidates qualify: deepseek-v4-pro, glm-5.1, qwen3.6-max-preview. DeepSeek-v4-pro is picked because (a) it's the deepest dedicated reasoner of the three on math/logic benchmarks, (b) the verifier's job is structured scoring which suits its strengths, and (c) it has the 75% promo until 2026-05-05 making the choice cheap to validate.

### Cost envelope (estimate per deliberation)

Assuming 4 selected members + chair + verifier, no Stage 4 retry, ~3k tokens per council call, ~6k for synthesis, ~2k for verification:

| Call | Model | Tokens | Cost |
|---|---|---|---|
| 4 council | deepseek-v4-pro / glm-5.1 / qwen3.6-max-preview (rotation) | ~12k total | ~$0.06 |
| 1 chair | kimi-k2.6 | ~6k | ~$0.04 |
| 1 verifier | deepseek-v4-pro | ~2k | ~$0.01 |
| 1 classifier | gemini-2.5-flash (free) | ~500 | $0 |
| **Total** | | | **~$0.11** |

Comfortably below the guidebook's "low-cost setup" $1–3 estimate. Premium-setup pricing only kicks in if the user opts into `gemini/gemini-3-pro-preview` or `kimi/kimi-k2-thinking`.

## 3 — Parameter sizing analysis

| Param | Current | Verdict | New |
|---|---|---|---|
| `temperature` | 0.7 | Keep. Half the providers ignore/override it for reasoning anyway (DeepSeek-reasoner drops it, Kimi K2.5/K2.6 omit it, Kimi-thinking forces 1.0, GLM-5+ defaults to 1.0). 0.7 is the nominal value for the rest. | **0.7** |
| `max_tokens` | 4096 | Too tight. Reasoning models split CoT into separate `reasoning_content`, but the visible `content` (Stage 3 synthesis especially) is still capped here, and the chairperson emits a multi-section structured decision. | **8192** |
| `timeout` | 120s | Tight. `deepseek-v4-pro` reasoning at high effort and `gemini-2.5-pro` with dynamic `thinking_budget` routinely take 60–90s; 120s leaves no margin for a single retry. | **240s** |

These remain `query_llm()` keyword defaults — callers can still override per-call.

## 4 — `server/board/llm.py` changes

### 4.1 Bumped defaults

```python
async def query_llm(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,        # was 4096
    timeout: float = 240.0,        # was 120.0
    fallback: bool = True,
) -> LLMResponse:
```

### 4.2 DeepSeek `reasoning_effort` env support

In `_send_deepseek`, after building `kwargs`:

```python
# v4 family supports reasoning_effort; v3-era 'deepseek-reasoner' does not.
if provider_model.startswith(("deepseek-v4-", "deepseek-v5-")):
    effort = os.getenv("DEEPSEEK_REASONING_EFFORT")
    if effort:
        if effort not in {"low", "medium", "high", "max"}:
            raise RuntimeError(
                "DEEPSEEK_REASONING_EFFORT must be one of low|medium|high|max."
            )
        kwargs["reasoning_effort"] = effort
```

Existing temperature-drop rule extends to v4-pro thinking mode (which silently ignores temperature):

```python
# v4-pro defaults to high reasoning effort and silently ignores temperature.
# deepseek-reasoner is the v3-era thinking alias, same behavior.
if provider_model not in {"deepseek-reasoner", "deepseek-v4-pro"}:
    kwargs["temperature"] = temperature
```

(`deepseek-v4-flash` respects temperature unless `DEEPSEEK_REASONING_EFFORT=high|max` is set; the operator owns that tradeoff via env.)

### 4.3 Kimi K2.6 quirk

The handler currently treats only `kimi-k2.5` as "omit temperature". Per guidebook §3e, K2.6 also has `top_p` locked, `n=1` only, and inherits the K2.5 reject-temperature-in-body behavior in some SDK versions. To be safe, extend the omit-temperature branch:

```python
if provider_model.startswith("kimi-k2-thinking"):
    kwargs["temperature"] = 1.0
elif provider_model.startswith(("kimi-k2.5", "kimi-k2.6")):
    pass  # provider enforces fixed sampling; do not pass temperature
else:
    kwargs["temperature"] = temperature
```

### 4.4 Qwen 3.6 `preserve_thinking`

In `_send_qwen`, after the existing `enable_thinking` / `thinking_budget` block:

```python
qwen_preserve = _env_bool("QWEN_PRESERVE_THINKING")
if qwen_preserve is not None:
    # qwen3.6-* introduces preserve_thinking for multi-turn agentic flows.
    # Older models silently ignore it; safe to always pass when set.
    kwargs["preserve_thinking"] = qwen_preserve
```

### 4.5 Gemini thinking control

In `_send_gemini`, replace the bare `GenerateContentConfig(...)` construction with one that honours per-family thinking config:

```python
config_kwargs: dict[str, Any] = {
    "system_instruction": system,
    "temperature": temperature,
    "max_output_tokens": max_tokens,
}

if provider_model.startswith("gemini-2.5"):
    budget_env = _read_optional_int_env("GEMINI_THINKING_BUDGET")
    if budget_env is not None:
        # 0 disables, -1 = dynamic, 0..32k = explicit cap
        config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
            thinking_budget=budget_env
        )
elif provider_model.startswith("gemini-3"):
    level = os.getenv("GEMINI_THINKING_LEVEL")
    if level:
        if level not in {"minimal", "low", "medium", "high"}:
            raise RuntimeError(
                "GEMINI_THINKING_LEVEL must be one of minimal|low|medium|high."
            )
        config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
            thinking_level=level
        )

config = genai_types.GenerateContentConfig(**config_kwargs)
```

`_read_optional_int_env` already exists; we relax its non-negative guard for this caller (Gemini accepts `-1`):

```python
def _read_optional_int_env(name: str, *, allow_negative: bool = False) -> int | None:
    ...
    if not allow_negative and parsed < 0:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return parsed
```

Existing `QWEN_THINKING_BUDGET` keeps `allow_negative=False` (default).

### 4.6 Fallback chain

No changes. The existing chain `[gemini-2.5-flash, glm-4.5-flash, qwen-flash]` + paid `deepseek-chat` is the right free-first path. `deepseek-chat` retires 2026-07-24 — that migration is tracked separately, not in this spec.

## 5 — `server/board/config.py` changes

```python
DEFAULT_CHAIRMAN_MODEL = "kimi/kimi-k2.6"               # was kimi/kimi-k2.5
DEFAULT_COUNCIL_MODELS = [
    "deepseek/deepseek-v4-pro",
    "glm/glm-5.1",
    "qwen/qwen3.6-max-preview",
]                                                        # was [deepseek-chat, kimi-k2.5]
DEFAULT_CLASSIFIER_MODEL = "gemini/gemini-2.5-flash"     # was deepseek/deepseek-chat
DEFAULT_VERIFICATION_MODEL = "deepseek/deepseek-v4-pro"  # was deepseek/deepseek-chat
```

Verifier-decoupling check (`_assert_verifier_decoupled`) keeps passing: `provider_of(kimi/...) = moonshot` ≠ `provider_of(deepseek/...) = deepseek`.

The CLI `--budget` and module docstring references to the old defaults need a one-line refresh; nothing structural.

## 6 — `server/board/metrics.py` changes

Add the missing model rates so `--budget` doesn't fall back to the default rate for the new defaults. Existing entries kept; new lines below.

```python
# Latest reasoning models (April 2026)
"kimi/kimi-k2.6":              (0.95, 4.00),    # was (0.60, 2.50) — guidebook §3e
"deepseek/deepseek-v4-flash":  (0.14, 0.28),
"deepseek/deepseek-v4-pro":    (0.435, 0.87),   # 75% promo until 2026-05-05; full $1.74/$3.48 after
"glm/glm-5.1":                 (1.40, 4.40),
"glm/glm-5":                   (0.50, 2.08),
"glm/glm-4.7-flash":           (0.0, 0.0),      # free
"qwen/qwen3.6-max-preview":    (1.30, 7.80),
"qwen/qwen3.6-plus":           (0.325, 1.95),
"qwen/qwen3-max":              (0.78, 3.90),
"qwen/qwen3.5-plus":           (0.26, 1.56),
"gemini/gemini-3-pro-preview":     (3.00, 15.00),  # mid of $2-4 / $12-18 range
"gemini/gemini-3-flash-preview":   (0.25, 0.80),
"gemini/gemini-3-flash-lite-preview": (0.25, 1.50),
```

The existing `kimi/kimi-k2.6` entry of `(0.60, 2.50)` is wrong (copy of K2.5); fix to `(0.95, 4.00)` per guidebook §3e.

DeepSeek-v4-pro post-promo rate (`$1.74 / $3.48`) is documented in a comment only, NOT applied — the spec assumes the promo is active. A follow-up bump after 2026-05-05 is the operator's call, not auto-handled here.

## 7 — `docs/LLM_PROVIDERS_GUIDEBOOK.md` changes

Add a Qwen 3.6 block at the **top** of the §3c table (above `qwen3-max`). Existing `qwen3-max` / `qwen3.5-*` rows stay for operators who haven't migrated.

```
| Model ID                  | Tier   | Strength                                | Context | Thinking            | $ in / $ out / 1M tok |
| ------------------------- | ------ | --------------------------------------- | ------- | ------------------- | --------------------- |
| `qwen3.6-max-preview`     | Paid   | 2026 flagship; #1 on SWE-bench Pro, Terminal-Bench 2.0, SkillsBench, etc. | 260k | yes + `preserve_thinking` | $1.30 / $7.80 |
| `qwen3.6-plus`            | Paid   | Production agentic coding; 78.8% SWE-Bench | 1M  | yes + `preserve_thinking` | $0.325 / $1.95       |
| `qwen3.6-27b`             | Open-weights (Apache 2.0) | Dense; multimodal; 262k → 1M extensible | 262k | yes (Thinking Preservation) | self-host |
| `qwen3.6-35b-a3b`         | Open-weights (Apache 2.0) | MoE variant                            | (vary) | yes                 | self-host             |
```

Append to §3c "Quirks":

```
- `qwen3.6-*` introduces `preserve_thinking=bool` for multi-turn agentic
  flows (preserves prior thinking traces across turns). Wired up via
  `QWEN_PRESERVE_THINKING` env. Older models silently ignore the kwarg.
- `qwen3.6-*` is also exposed via Alibaba Cloud's compatible-mode endpoint
  with both OpenAI and Anthropic API shapes — but the board uses the
  native DashScope path, not compatible-mode.
```

Add to §8 "Common gotchas" a deprecation marker:

```
- Qwen `qwen3.6-max-preview` is a **preview** model — Alibaba previews
  have historically been promoted to a stable id (e.g., `qwen3.6-max`)
  within ~60 days. Watch the changelog before pinning it for production.
```

Update the §1 "Defaults" paragraph to reflect the new defaults:

> Defaults in `server/board/config.py` use `kimi/kimi-k2.6` (chairperson),
> `[deepseek-v4-pro, glm-5.1, qwen3.6-max-preview]` (council),
> `gemini/gemini-2.5-flash` (classifier, free tier), and
> `deepseek/deepseek-v4-pro` (verifier, ≠ chairperson). A brand-new install
> needs `MOONSHOT_API_KEY`, `DEEPSEEK_API_KEY`, `ZAI_API_KEY`,
> `DASHSCOPE_API_KEY` (with `DASHSCOPE_REGION=international`), and
> `GEMINI_API_KEY`.

Also update the §4 "Recommendations by board role" table — add a column or new "2026-04 reasoning default" row showing the chosen model per role.

Update §5 "The board's defaults" code block to show `max_tokens=8192` and `timeout=240.0`.

## 8 — Risks / things to watch

1. **`qwen3.6-max-preview` is a preview model.** It can be renamed or rate-limited without notice. Mitigation: documented in §7 above; `qwen/qwen3.6-plus` is the production fallback if it disappears.
2. **DeepSeek-v4-pro 75% promo ends 2026-05-05.** Post-promo cost is 4× current. `--budget` will under-report until rates are bumped — flagged in metrics.py comment but not auto-handled.
3. **Verifier on the same family as a council member** (both deepseek). Verifier-decoupling only checks against chairperson, but deepseek appearing in both council pool and verifier seat could give that family disproportionate influence if its turn lands on the council too. Acceptable with 3-model round-robin; revisit if council shrinks.
4. **Kimi K2.6 omit-temperature** is conservative — guidebook §3e implies "other Kimi models accept caller's temperature" but K2.6 is the current flagship and shares K2.5 sampling locks per Moonshot's 2026-04 docs. If K2.6 turns out to accept temperature, the only cost of omitting it is loss of 0.7 → provider-default (≈0.6). Acceptable.
5. **Gemini free tier rate limits** (5–15 RPM, 250k tok/min cap across all free models). A single deliberation does ~1 classifier call so it's well under, but parallel deliberations could throttle. Mitigation: classifier failures fall through the existing `LLMProviderError` chain to a paid model.

## 9 — Validation plan

Per guidebook §9, smoke each new model individually before flipping the defaults:

```bash
uv run pytest -m live tests/test_llm_live_smoke.py -v
```

Then run a single-member deliberation against each new default in turn:

```bash
uv run python -m server.cli --members strategist --budget \
  "Should we ship a free tier for the SaaS launch?"
uv run python -m server.cli --members critic --budget "..."
uv run python -m server.cli --verify --budget "..."
```

Verify `--budget` shows non-default rates for kimi-k2.6, deepseek-v4-pro, glm-5.1, qwen3.6-max-preview (i.e., metrics.py picked up the new entries).

No new unit tests are required by this spec — the changes are env-keyed config and are exercised by the live smoke suite.

## 10 — Rollout

Single PR. No phased rollout needed: the changes are self-contained config + handler tweaks, and `.env` overrides let operators pin the old defaults if anything regresses.
