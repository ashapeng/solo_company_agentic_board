# LLM Providers Reasoning Update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Default board to April 2026 reasoning models; integrate new handler quirks (DeepSeek `reasoning_effort`, Gemini thinking config, Qwen `preserve_thinking`, Kimi K2.6 sampling locks); right-size call defaults for reasoning workloads.

**Architecture:** Edits in 4 files. No new files, no new abstractions. Each handler change isolated; tests added to existing per-provider test files following the `_FakeOpenAI` / `monkeypatch.setenv` pattern.

**Tech Stack:** Python 3.11+, pytest, openai SDK, google-genai, dashscope, zai-sdk, httpx.

**Spec:** `docs/superpowers/specs/2026-04-25-llm-providers-reasoning-update-design.md`

---

## File map

| File | Action | Why |
|---|---|---|
| `server/board/metrics.py` | Modify (add cost rates, fix kimi-k2.6) | Task 1 |
| `tests/test_llm_metrics_pricing.py` | Modify (parametrize new models) | Task 1 |
| `server/board/llm.py` | Modify (defaults bump) | Task 2 |
| `server/board/llm.py` | Modify (Kimi K2.6 quirk) | Task 3 |
| `tests/test_llm_kimi.py` | Modify (K2.6 test) | Task 3 |
| `server/board/llm.py` | Modify (DeepSeek effort + v4-pro temp) | Task 4 |
| `tests/test_llm_deepseek.py` | Modify (effort + v4-pro tests) | Task 4 |
| `server/board/llm.py` | Modify (Qwen preserve_thinking) | Task 5 |
| `tests/test_llm_qwen.py` | Modify (preserve_thinking test) | Task 5 |
| `server/board/llm.py` | Modify (Gemini thinking + helper relax) | Task 6 |
| `tests/test_llm_gemini.py` | Modify (thinking_budget/level tests) | Task 6 |
| `server/board/config.py` | Modify (swap defaults) | Task 7 |
| `docs/LLM_PROVIDERS_GUIDEBOOK.md` | Modify (Qwen 3.6 + new defaults) | Task 8 |

---

## Task 1: Add cost rates for new reasoning models

**Files:**
- Modify: `server/board/metrics.py:31-42` (COST_RATES dict)
- Modify: `tests/test_llm_metrics_pricing.py:18-32`

- [ ] **Step 1: Inspect current COST_RATES**

Run: `grep -n "COST_RATES\|kimi-k2.6\|deepseek/deepseek-chat" server/board/metrics.py`
Confirm `kimi/kimi-k2.6` row present and currently `(0.60, 2.50)`.

- [ ] **Step 2: Write failing parametrized test**

Edit `tests/test_llm_metrics_pricing.py`. Add new parametrize block above `test_estimate_cost_strips_openrouter_prefix`:

```python
@pytest.mark.parametrize("model,in_rate,out_rate", [
    ("kimi/kimi-k2.6",                       0.95, 4.00),
    ("deepseek/deepseek-v4-flash",           0.14, 0.28),
    ("deepseek/deepseek-v4-pro",             0.435, 0.87),
    ("glm/glm-5.1",                          1.40, 4.40),
    ("glm/glm-5",                            0.50, 2.08),
    ("glm/glm-4.7-flash",                    0.0, 0.0),
    ("qwen/qwen3.6-max-preview",             1.30, 7.80),
    ("qwen/qwen3.6-plus",                    0.325, 1.95),
    ("qwen/qwen3-max",                       0.78, 3.90),
    ("qwen/qwen3.5-plus",                    0.26, 1.56),
    ("gemini/gemini-3-pro-preview",          3.00, 15.00),
    ("gemini/gemini-3-flash-preview",        0.25, 0.80),
    ("gemini/gemini-3-flash-lite-preview",   0.25, 1.50),
])
def test_reasoning_models_have_expected_rates(model, in_rate, out_rate):
    actual_in, actual_out = metrics.COST_RATES[model]
    assert actual_in == in_rate
    assert actual_out == out_rate
```

- [ ] **Step 3: Run test, expect FAIL**

Run: `uv run pytest tests/test_llm_metrics_pricing.py::test_reasoning_models_have_expected_rates -v`
Expected: 13 failures (KeyError or wrong-value assertion for kimi-k2.6).

- [ ] **Step 4: Update COST_RATES in metrics.py**

In `server/board/metrics.py`, locate the `COST_RATES` dict (around line 31-42). Replace the `"kimi/kimi-k2.6"` entry and append new rows. Final block should look like:

```python
    "kimi/kimi-k2.5":             (0.60, 3.00),
    "kimi/kimi-k2.6":             (0.95, 4.00),    # was (0.60, 2.50) — guidebook §3e
    # Latest reasoning models (April 2026)
    "deepseek/deepseek-v4-flash":  (0.14, 0.28),
    "deepseek/deepseek-v4-pro":    (0.435, 0.87),  # 75% promo until 2026-05-05; full $1.74/$3.48 after
    "glm/glm-5.1":                 (1.40, 4.40),
    "glm/glm-5":                   (0.50, 2.08),
    "glm/glm-4.7-flash":           (0.0, 0.0),     # free
    "qwen/qwen3.6-max-preview":    (1.30, 7.80),
    "qwen/qwen3.6-plus":           (0.325, 1.95),
    "qwen/qwen3-max":              (0.78, 3.90),
    "qwen/qwen3.5-plus":           (0.26, 1.56),
    "gemini/gemini-3-pro-preview":        (3.00, 15.00),
    "gemini/gemini-3-flash-preview":      (0.25, 0.80),
    "gemini/gemini-3-flash-lite-preview": (0.25, 1.50),
```

(If the existing kimi-k2.5 line uses `(0.60, 2.50)`, leave it alone — guidebook lists `$0.60/$3.00` but the current file may differ; only the kimi-k2.6 line MUST change.)

- [ ] **Step 5: Re-run test, expect PASS**

Run: `uv run pytest tests/test_llm_metrics_pricing.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/board/metrics.py tests/test_llm_metrics_pricing.py
git commit -m "feat(metrics): add cost rates for april 2026 reasoning models"
```

---

## Task 2: Bump query_llm defaults for reasoning

**Files:**
- Modify: `server/board/llm.py:813-822` (query_llm signature)

- [ ] **Step 1: Confirm current defaults**

Run: `grep -n "max_tokens: int = \|timeout: float = " server/board/llm.py`
Expected: `max_tokens: int = 4096,` and `timeout: float = 120.0,` on the `query_llm` signature.

- [ ] **Step 2: Edit signature**

In `server/board/llm.py`, find the `query_llm` definition (around line 813) and change:

```python
async def query_llm(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,        # was 4096 — reasoning models need headroom
    timeout: float = 240.0,        # was 120.0 — deep reasoning takes 60-90s
    fallback: bool = True,
) -> LLMResponse:
```

- [ ] **Step 3: Run full llm test suite, expect PASS**

Run: `uv run pytest tests/test_llm_routing.py tests/test_llm_fallback.py tests/test_llm_deepseek.py tests/test_llm_kimi.py tests/test_llm_qwen.py tests/test_llm_gemini.py tests/test_llm_zai.py tests/test_llm_openrouter.py -v`
Expected: all pass. If any test depends on the old defaults (unlikely — tests pass explicit values), update that test to pin its own values.

- [ ] **Step 4: Commit**

```bash
git add server/board/llm.py
git commit -m "feat(llm): bump query_llm defaults for reasoning workloads (max_tokens 8192, timeout 240s)"
```

---

## Task 3: Kimi K2.6 omit-temperature

**Files:**
- Modify: `server/board/llm.py:340-346` (Kimi temperature branches in `_send_kimi`)
- Modify: `tests/test_llm_kimi.py` (add K2.6 test)

- [ ] **Step 1: Write failing test**

Open `tests/test_llm_kimi.py`. Find an existing K2.5 omit-temperature test for the pattern. Append:

```python
async def test_kimi_k26_omits_temperature(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "kimi/kimi-k2.6",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create
```

(If `_FakeOpenAI` is named differently in this file, match the existing local fixture name.)

- [ ] **Step 2: Run test, expect FAIL**

Run: `uv run pytest tests/test_llm_kimi.py::test_kimi_k26_omits_temperature -v`
Expected: AssertionError — `temperature` IS in `last_create` (currently routes through the `else` branch).

- [ ] **Step 3: Update Kimi handler**

In `server/board/llm.py`, find the per-model temperature block in `_send_kimi` (around line 340-346):

```python
    # Per-model temperature rules
    if provider_model.startswith("kimi-k2-thinking"):
        kwargs["temperature"] = 1.0
    elif provider_model.startswith("kimi-k2.5"):
        pass  # provider enforces fixed sampling; do not pass temperature
    else:
        kwargs["temperature"] = temperature
```

Replace with:

```python
    # Per-model temperature rules
    if provider_model.startswith("kimi-k2-thinking"):
        kwargs["temperature"] = 1.0
    elif provider_model.startswith(("kimi-k2.5", "kimi-k2.6")):
        # K2.5/K2.6: provider enforces fixed sampling; do not pass temperature
        pass
    else:
        kwargs["temperature"] = temperature
```

- [ ] **Step 4: Re-run test, expect PASS**

Run: `uv run pytest tests/test_llm_kimi.py -v`
Expected: all kimi tests pass (including the existing K2.5 test).

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_kimi.py
git commit -m "feat(llm): omit temperature for kimi-k2.6 (matches k2.5 sampling locks)"
```

---

## Task 4: DeepSeek `reasoning_effort` env + v4-pro temperature drop

**Files:**
- Modify: `server/board/llm.py:269-281` (`_send_deepseek` kwargs assembly)
- Modify: `tests/test_llm_deepseek.py` (add v4-pro and effort tests)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_deepseek.py`:

```python
async def test_deepseek_v4_pro_omits_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-v4-pro",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create


async def test_deepseek_v4_flash_passes_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hi"}],
            temperature=0.4,
        )
    assert _FakeOpenAI.last_create["temperature"] == 0.4
    assert "reasoning_effort" not in _FakeOpenAI.last_create


async def test_deepseek_v4_reasoning_effort_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "high")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hi"}],
        )
    assert _FakeOpenAI.last_create["reasoning_effort"] == "high"


async def test_deepseek_reasoning_effort_invalid_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "extreme")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        with pytest.raises(RuntimeError, match="DEEPSEEK_REASONING_EFFORT"):
            await llm.query_llm(
                "deepseek/deepseek-v4-flash",
                [{"role": "user", "content": "hi"}],
            )


async def test_deepseek_reasoning_effort_ignored_for_chat(monkeypatch):
    """Effort env must NOT be sent for non-v4 models — guards against silent
    400s on the legacy deepseek-chat endpoint."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "high")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-chat",
            [{"role": "user", "content": "hi"}],
        )
    assert "reasoning_effort" not in _FakeOpenAI.last_create
```

- [ ] **Step 2: Run tests, expect FAIL**

Run: `uv run pytest tests/test_llm_deepseek.py -v`
Expected: 5 new tests fail.

- [ ] **Step 3: Update `_send_deepseek` kwargs block**

In `server/board/llm.py`, find `_send_deepseek` (starts ~line 252). The kwargs assembly currently looks like:

```python
    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }
    if provider_model != "deepseek-reasoner":
        kwargs["temperature"] = temperature
```

Replace with:

```python
    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }
    # v4-pro defaults to high reasoning effort and silently ignores temperature.
    # deepseek-reasoner is the v3-era thinking alias — same behavior.
    if provider_model not in {"deepseek-reasoner", "deepseek-v4-pro"}:
        kwargs["temperature"] = temperature

    # reasoning_effort is a v4-only knob; older models 400 if it's sent.
    if provider_model.startswith("deepseek-v4-"):
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT")
        if effort:
            if effort not in {"low", "medium", "high", "max"}:
                raise RuntimeError(
                    "DEEPSEEK_REASONING_EFFORT must be one of low|medium|high|max."
                )
            kwargs["reasoning_effort"] = effort
```

- [ ] **Step 4: Re-run tests, expect PASS**

Run: `uv run pytest tests/test_llm_deepseek.py -v`
Expected: all pass (existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_deepseek.py
git commit -m "feat(llm): deepseek v4 reasoning_effort env + v4-pro temperature drop"
```

---

## Task 5: Qwen `preserve_thinking` env

**Files:**
- Modify: `server/board/llm.py:485-490` (Qwen kwargs after `enable_thinking` block)
- Modify: `tests/test_llm_qwen.py` (add preserve_thinking test)

- [ ] **Step 1: Write failing test**

Append to `tests/test_llm_qwen.py` (use the existing test file's fake-Generation pattern; the snippet below assumes a `_FakeGeneration.last_kwargs` dict per existing tests — adapt to whatever variable that file uses):

```python
async def test_qwen_preserve_thinking_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("QWEN_PRESERVE_THINKING", "true")
    # ... use the file's existing fake-dashscope fixture ...
    await llm.query_llm(
        "qwen/qwen3.6-max-preview",
        [{"role": "user", "content": "hi"}],
    )
    assert _FakeGeneration.last_kwargs["preserve_thinking"] is True


async def test_qwen_preserve_thinking_omitted_when_unset(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.delenv("QWEN_PRESERVE_THINKING", raising=False)
    # ... fake-dashscope ...
    await llm.query_llm(
        "qwen/qwen3.6-max-preview",
        [{"role": "user", "content": "hi"}],
    )
    assert "preserve_thinking" not in _FakeGeneration.last_kwargs
```

(Read the existing tests in this file first to learn the fixture name and adapt — the pattern matches the deepseek/kimi files but uses `dashscope.Generation.call`.)

- [ ] **Step 2: Run tests, expect FAIL**

Run: `uv run pytest tests/test_llm_qwen.py -v`
Expected: 2 new tests fail.

- [ ] **Step 3: Update `_send_qwen`**

In `server/board/llm.py`, find the existing `qwen_thinking` / `qwen_budget` block in `_send_qwen` (around line 485-490). Append below it:

```python
    qwen_preserve = _env_bool("QWEN_PRESERVE_THINKING")
    if qwen_preserve is not None:
        # qwen3.6-* uses preserve_thinking for multi-turn agentic flows.
        # Older models silently ignore it; safe to pass when explicitly set.
        kwargs["preserve_thinking"] = qwen_preserve
```

- [ ] **Step 4: Re-run tests, expect PASS**

Run: `uv run pytest tests/test_llm_qwen.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_qwen.py
git commit -m "feat(llm): qwen preserve_thinking env for qwen3.6 multi-turn flows"
```

---

## Task 6: Gemini thinking config (2.5 budget + 3.x level)

**Files:**
- Modify: `server/board/llm.py:92-102` (`_read_optional_int_env` helper)
- Modify: `server/board/llm.py:574-578` (`_send_gemini` config build)
- Modify: `tests/test_llm_gemini.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_gemini.py` (mirror the file's existing fake-genai fixture):

```python
async def test_gemini_25_thinking_budget_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "1024")
    # ... existing fake-genai fixture ...
    await llm.query_llm(
        "gemini/gemini-2.5-pro",
        [{"role": "user", "content": "hi"}],
    )
    cfg = _captured_config  # from fake fixture
    assert cfg.thinking_config.thinking_budget == 1024


async def test_gemini_25_thinking_budget_negative_one_dynamic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("GEMINI_THINKING_BUDGET", "-1")
    await llm.query_llm("gemini/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
    assert _captured_config.thinking_config.thinking_budget == -1


async def test_gemini_3_thinking_level_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "high")
    await llm.query_llm(
        "gemini/gemini-3-pro-preview",
        [{"role": "user", "content": "hi"}],
    )
    assert _captured_config.thinking_config.thinking_level == "high"


async def test_gemini_3_thinking_level_invalid_raises(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("GEMINI_THINKING_LEVEL", "extreme")
    with pytest.raises(RuntimeError, match="GEMINI_THINKING_LEVEL"):
        await llm.query_llm(
            "gemini/gemini-3-pro-preview",
            [{"role": "user", "content": "hi"}],
        )


async def test_gemini_25_no_thinking_when_env_unset(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.delenv("GEMINI_THINKING_BUDGET", raising=False)
    await llm.query_llm("gemini/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
    # thinking_config should be unset (None) when env not provided
    assert getattr(_captured_config, "thinking_config", None) is None
```

(Read the file to learn the fixture name for `_captured_config`. Existing gemini tests already capture `GenerateContentConfig` somehow — extend that capture to include `thinking_config`.)

- [ ] **Step 2: Run tests, expect FAIL**

Run: `uv run pytest tests/test_llm_gemini.py -v`
Expected: 5 new tests fail.

- [ ] **Step 3: Relax `_read_optional_int_env` to allow negative**

In `server/board/llm.py`, find `_read_optional_int_env` (around line 92). Change:

```python
def _read_optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError as e:
        raise RuntimeError(f"{name} must be an integer.") from e
    if parsed < 0:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return parsed
```

to:

```python
def _read_optional_int_env(name: str, *, allow_negative: bool = False) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError as e:
        raise RuntimeError(f"{name} must be an integer.") from e
    if not allow_negative and parsed < 0:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return parsed
```

(Existing call site `_read_optional_int_env("QWEN_THINKING_BUDGET")` keeps default `allow_negative=False` — backwards compatible.)

- [ ] **Step 4: Update `_send_gemini` config build**

In `server/board/llm.py`, find this block in `_send_gemini` (around line 574-578):

```python
    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
```

Replace with:

```python
    config_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }

    if provider_model.startswith("gemini-2.5"):
        budget = _read_optional_int_env("GEMINI_THINKING_BUDGET", allow_negative=True)
        if budget is not None:
            # 0 disables; -1 = dynamic; 0..32k = explicit cap.
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_budget=budget
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

- [ ] **Step 5: Re-run tests, expect PASS**

Run: `uv run pytest tests/test_llm_gemini.py -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add server/board/llm.py tests/test_llm_gemini.py
git commit -m "feat(llm): gemini thinking config (2.5 budget + 3.x level)"
```

---

## Task 7: Swap board defaults to reasoning models

**Files:**
- Modify: `server/board/config.py:13-19` (DEFAULT_* constants)

- [ ] **Step 1: Confirm current defaults**

Run: `grep -n "DEFAULT_CHAIRMAN_MODEL\|DEFAULT_COUNCIL_MODELS\|DEFAULT_CLASSIFIER_MODEL\|DEFAULT_VERIFICATION_MODEL" server/board/config.py`

- [ ] **Step 2: Replace defaults block**

In `server/board/config.py`, replace lines 13-19:

```python
DEFAULT_CHAIRMAN_MODEL = "kimi/kimi-k2.5"
DEFAULT_COUNCIL_MODELS = [
    "deepseek/deepseek-chat",
    "kimi/kimi-k2.5",
]
DEFAULT_CLASSIFIER_MODEL = "deepseek/deepseek-chat"
DEFAULT_VERIFICATION_MODEL = "deepseek/deepseek-chat"
```

with:

```python
DEFAULT_CHAIRMAN_MODEL = "kimi/kimi-k2.6"
DEFAULT_COUNCIL_MODELS = [
    "deepseek/deepseek-v4-pro",
    "glm/glm-5.1",
    "qwen/qwen3.6-max-preview",
]
DEFAULT_CLASSIFIER_MODEL = "gemini/gemini-2.5-flash"
DEFAULT_VERIFICATION_MODEL = "deepseek/deepseek-v4-pro"
```

- [ ] **Step 3: Verify boot — verifier-decoupling check still passes**

Run: `uv run python -c "import server.board.config"`
Expected: no exception. The check `_assert_verifier_decoupled()` runs at import; chair=moonshot, verifier=deepseek → pass.

- [ ] **Step 4: Run config-touching tests**

Run: `uv run pytest tests/test_board_contract.py tests/test_board_core_contracts.py tests/test_full_council_contract.py tests/test_first_member_contract.py tests/test_verification_contract.py -v`
Expected: all pass. If a test pins one of the OLD defaults as a string literal, update it.

- [ ] **Step 5: Commit**

```bash
git add server/board/config.py
git commit -m "feat(config): default board to april 2026 reasoning models"
```

---

## Task 8: Update guidebook with Qwen 3.6 + new defaults

**Files:**
- Modify: `docs/LLM_PROVIDERS_GUIDEBOOK.md` (multiple sections)

- [ ] **Step 1: Add Qwen 3.6 rows to §3c table**

In `docs/LLM_PROVIDERS_GUIDEBOOK.md`, find the §3c Qwen table (the `| Model ID | Tier | ...` table starting around line 192). Insert these rows ABOVE the existing `qwen3-max` row:

```
| `qwen3.6-max-preview`     | Paid              | 2026 flagship; #1 SWE-bench Pro/Terminal-Bench 2.0/SkillsBench | 260k | yes + `preserve_thinking` | $1.30 / $7.80 |
| `qwen3.6-plus`            | Paid              | Production agentic coding; 78.8% SWE-Bench | 1M | yes + `preserve_thinking` | $0.325 / $1.95 |
| `qwen3.6-27b`             | Open-weights (Apache 2.0) | Dense; multimodal; 262k → 1M extensible | 262k | yes (Thinking Preservation) | self-host |
| `qwen3.6-35b-a3b`         | Open-weights (Apache 2.0) | MoE variant | (vary) | yes | self-host |
```

- [ ] **Step 2: Append Qwen 3.6 quirks**

In §3c "Quirks" bullet list (right after the existing `Default temperature` bullet around line 217), append:

```markdown
- `qwen3.6-*` introduces `preserve_thinking=bool` for multi-turn agentic
  flows (preserves prior thinking traces across turns). Wired up via
  `QWEN_PRESERVE_THINKING` env. Older models silently ignore the kwarg.
- `qwen3.6-*` is also exposed via Alibaba Cloud's compatible-mode endpoint
  with both OpenAI and Anthropic API shapes — but the board uses the
  native DashScope path, not compatible-mode.
```

- [ ] **Step 3: Add Qwen preview gotcha to §8**

In §8 "Common gotchas", append a new bullet:

```markdown
- **Qwen `qwen3.6-max-preview` is a preview model.** Alibaba previews
  have historically been promoted to a stable id (e.g., `qwen3.6-max`)
  within ~60 days. Watch the changelog before pinning it for production;
  `qwen/qwen3.6-plus` is the production-grade fallback.
```

- [ ] **Step 4: Update §1 defaults paragraph**

Find the paragraph in §1 starting `Defaults in \`server/board/config.py\` use \`kimi/kimi-k2.5\`...` (around line 37-39). Replace with:

```markdown
Defaults in `server/board/config.py` use `kimi/kimi-k2.6` (chairperson),
`[deepseek-v4-pro, glm-5.1, qwen3.6-max-preview]` (council),
`gemini/gemini-2.5-flash` (classifier — free tier), and
`deepseek/deepseek-v4-pro` (verifier — different provider from chairperson).
A brand-new install with all defaults active needs `MOONSHOT_API_KEY`,
`DEEPSEEK_API_KEY`, `ZAI_API_KEY`, `DASHSCOPE_API_KEY` (with
`DASHSCOPE_REGION=international`), and `GEMINI_API_KEY`.
```

- [ ] **Step 5: Update §5 defaults code block**

Find the `# server/board/llm.py` code block in §5 (around line 341-345). Replace with:

```python
# server/board/llm.py
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 8192    # was 4096; bumped for reasoning-model headroom
DEFAULT_TIMEOUT = 240.0      # was 120.0; deep reasoning takes 60-90s
```

- [ ] **Step 6: Update §4 recommendations table**

In §4 "Recommendations by board role", note the project default per role by adding a new column header or a sentence below the table. Append after the existing footnote `\* Verifier MUST be...`:

```markdown

**2026-04 project defaults** (`server/board/config.py`):
Chairperson `kimi/kimi-k2.6` · Council `[deepseek-v4-pro, glm-5.1, qwen3.6-max-preview]` ·
Classifier `gemini/gemini-2.5-flash` · Verifier `deepseek/deepseek-v4-pro`.
```

- [ ] **Step 7: Sanity-check the file renders**

Run: `head -50 docs/LLM_PROVIDERS_GUIDEBOOK.md && grep -n "qwen3.6\|kimi-k2.6\|deepseek-v4-pro" docs/LLM_PROVIDERS_GUIDEBOOK.md | head -20`
Expected: Qwen 3.6 rows appear in §3c; new defaults paragraph in §1; updated defaults code block in §5.

- [ ] **Step 8: Commit**

```bash
git add docs/LLM_PROVIDERS_GUIDEBOOK.md
git commit -m "docs(llm): add qwen 3.6 family + 2026-04 reasoning defaults to guidebook"
```

---

## Final validation

- [ ] **Step 1: Full test suite**

Run: `uv run pytest tests/test_llm_*.py tests/test_board_*.py tests/test_full_council_contract.py tests/test_first_member_contract.py tests/test_verification_contract.py -v`
Expected: all pass.

- [ ] **Step 2: Boot smoke**

Run: `uv run python -c "from server.board.config import get_chairman_model, get_council_models, get_verification_model, get_classifier_model; print(get_chairman_model(), get_council_models(), get_classifier_model(), get_verification_model())"`
Expected: `kimi/kimi-k2.6 ['deepseek/deepseek-v4-pro', 'glm/glm-5.1', 'qwen/qwen3.6-max-preview'] gemini/gemini-2.5-flash deepseek/deepseek-v4-pro`

- [ ] **Step 3 (optional, gated): Live smoke per provider**

Operator-run only (needs real keys):

```bash
uv run pytest -m live tests/test_llm_live_smoke.py -v
```

If any new model 404s, the model id is wrong — fix in config.py and re-run.

---

## Self-review notes

Spec coverage: §2 → Task 7. §3 → Task 2. §4.1 → Task 2. §4.2 → Task 4. §4.3 → Task 3. §4.4 → Task 5. §4.5 → Task 6. §5 → Task 7. §6 → Task 1. §7 → Task 8. §8 risks → tracked in spec, no plan tasks needed (all are runtime/operational). §9 validation → Final validation block.

No placeholders. All code blocks self-contained. No "similar to Task N" references.
