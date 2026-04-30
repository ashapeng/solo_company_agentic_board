"""Token and cost tracking for board deliberation sessions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CallMetrics:
    """Metrics for a single LLM call."""
    member_id: str
    stage: int
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    finish_reason: str | None = None
    response_id: str | None = None


# Cost rates per 1M tokens: {model_prefix: (input_rate, output_rate)}
COST_RATES: dict[str, tuple[float, float]] = {
    # OpenRouter-keyed (used when model id starts with 'openrouter:')
    "anthropic/claude-opus-4": (15.0, 75.0),
    "anthropic/claude-sonnet-4": (3.0, 15.0),
    "openai/gpt-4.1": (2.0, 8.0),
    "google/gemini-2.5-pro": (1.25, 10.0),
    "x-ai/grok-3": (3.0, 15.0),

    # Native-prefix rows (USD per 1M tokens, input / output)
    "gemini/gemini-2.5-flash":    (0.0, 0.0),    # AI Studio free tier
    "gemini/gemini-2.5-pro":      (1.25, 10.0),  # paid AI Studio
    "glm/glm-4.5-flash":          (0.0, 0.0),    # Z.AI free
    "glm/glm-4.6":                (0.6, 2.2),    # Z.AI paid (approximate)
    # --- Qwen / DashScope ---
    "qwen/qwen-flash":            (0.0, 0.0),    # DashScope free quota (Singapore)
    "qwen/qwen-turbo":            (0.05, 0.20),
    "qwen/qwen-plus":             (0.4, 1.2),
    "qwen/qwen-max":              (1.6, 6.4),
    # Qwen 3.6 series (2026-04)
    "qwen/qwen3.6-max-preview":    (1.30, 7.80),
    "qwen/qwen3.6-plus":           (0.325, 1.95),
    "qwen/qwen3.6-plus-2026-04-02":(0.325, 1.95),   # dated snapshot of plus
    "qwen/qwen3.6-flash":          (0.065, 0.26),  # paid + free quota
    "qwen/qwen3.6-flash-2026-04-16":(0.065, 0.26),  # dated snapshot of flash
    "qwen/qwen3.6-27b":            (0.0, 0.0),     # open-weight Apache 2.0 (self-host or API free)
    "qwen/qwen3.6-35b-a3b":        (0.0, 0.0),     # MoE open-weight Apache 2.0 (self-host)
    # Qwen 3.5 series
    "qwen/qwen3-max":              (0.78, 3.90),
    "qwen/qwen3.5-plus":           (0.26, 1.56),
    "qwen/qwen3.5-plus-2026-02-15": (0.26, 1.56),  # dated snapshot
    "qwen/qwen3.5-plus-2026-04-20": (0.26, 1.56),  # dated snapshot
    "qwen/qwen3.5-flash-2026-02-23":(0.065, 0.26),  # dated flash
    "qwen/qwen3.5-27b":            (0.0, 0.0),     # open-weight (self-host)
    "qwen/qwen3.5-35b-a3b":        (0.0, 0.0),     # MoE open-weight (self-host)
    "qwen/qwen3.5-122b-a10b":      (0.0, 0.0),     # large MoE open-weight (self-host)
    "qwen/qwen3.5-397b-a17b":      (0.0, 0.0),     # ultra-large MoE open-weight (self-host)
    # --- DeepSeek ---
    # V4 series (current — https://api-docs.deepseek.com/quick_start/pricing)
    "deepseek/deepseek-v4-flash":  (0.14, 0.28),   # ¥1.00/¥2.00 per M tok CNY; cache-hit input ¥0.02
    "deepseek/deepseek-v4-pro":    (0.435, 0.87),  # 75% promo (¥3/¥6 CNY) until 2026-05-05; full price (¥12/¥24) = $1.74/$3.48
    # Legacy aliases — will retire 2026-07-24; map to v4-flash under the hood
    "deepseek/deepseek-chat":     (0.14, 0.28),   # now alias → v4-flash non-thinking mode
    "deepseek/deepseek-reasoner": (0.14, 0.28),   # now alias → v4-flash thinking mode
    # --- GLM / Z.AI ---
    "glm/glm-5.1":                 (1.40, 4.40),
    "glm/glm-5":                   (0.50, 2.08),
    "glm/glm-4.7-flash":           (0.0, 0.0),     # free
    # --- Kimi / Moonshot ---
    "kimi/kimi-k2.5":             (0.60, 2.50),
    "kimi/kimi-k2.6":             (0.95, 4.00),    # was (0.60, 2.50) — guidebook §3e
    "gemini/gemini-3-pro-preview":        (3.00, 15.00),
    "gemini/gemini-3-flash-preview":      (0.25, 0.80),
    "gemini/gemini-3-flash-lite-preview": (0.25, 1.50),
}

# Fallback rate when model is not in the cost table
_DEFAULT_RATE: tuple[float, float] = (3.0, 15.0)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a single call.

    Tokens set to -1 (unknown) are treated as 0 for cost estimation. The
    'openrouter:' prefix is stripped before lookup so 'openrouter:google/...'
    resolves to the same row as the underlying OpenRouter model id.
    """
    key = model.split(":", 1)[1] if model.startswith("openrouter:") else model
    input_rate, output_rate = COST_RATES.get(key, _DEFAULT_RATE)

    in_tok = max(input_tokens, 0)
    out_tok = max(output_tokens, 0)

    return (in_tok * input_rate / 1_000_000) + (out_tok * output_rate / 1_000_000)


class SessionMetrics:
    """Tracks metrics across all LLM calls in a board session."""

    def __init__(self) -> None:
        self.calls: list[CallMetrics] = []

    def record(self, call: CallMetrics) -> None:
        """Record metrics from a single LLM call."""
        self.calls.append(call)

    def total_tokens(self) -> int:
        """Total tokens across all calls (unknown tokens counted as 0)."""
        total = 0
        for c in self.calls:
            total += max(c.input_tokens, 0) + max(c.output_tokens, 0)
        return total

    def total_cost_estimate(self) -> float:
        """Estimated total cost in USD across all calls."""
        return sum(
            _estimate_cost(c.model, c.input_tokens, c.output_tokens)
            for c in self.calls
        )

    def by_stage(self, stage: int) -> list[CallMetrics]:
        """Return all call metrics for a given stage."""
        return [c for c in self.calls if c.stage == stage]

    def summary(self) -> dict:
        """Return a summary dictionary of session metrics."""
        return {
            "total_calls": len(self.calls),
            "total_tokens": self.total_tokens(),
            "total_cost_estimate_usd": round(self.total_cost_estimate(), 4),
            "calls": [
                {
                    "member_id": c.member_id,
                    "stage": c.stage,
                    "model": c.model,
                    "input_tokens": c.input_tokens,
                    "output_tokens": c.output_tokens,
                    "latency_seconds": c.latency_seconds,
                    "finish_reason": c.finish_reason,
                    "response_id": c.response_id,
                }
                for c in self.calls
            ],
            "by_stage": {
                stage: {
                    "calls": len(stage_calls),
                    "tokens": sum(
                        max(c.input_tokens, 0) + max(c.output_tokens, 0)
                        for c in stage_calls
                    ),
                }
                for stage in (1, 2, 3)
                if (stage_calls := self.by_stage(stage))
            },
        }
