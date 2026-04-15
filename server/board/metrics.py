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


# Cost rates per 1M tokens: {model_prefix: (input_rate, output_rate)}
COST_RATES: dict[str, tuple[float, float]] = {
    "anthropic/claude-opus-4": (15.0, 75.0),
    "anthropic/claude-sonnet-4": (3.0, 15.0),
    "openai/gpt-4.1": (2.0, 8.0),
    "google/gemini-2.5-pro": (1.25, 10.0),
    "x-ai/grok-3": (3.0, 15.0),
}

# Fallback rate when model is not in the cost table
_DEFAULT_RATE: tuple[float, float] = (3.0, 15.0)


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a single call.

    Tokens set to -1 (unknown) are treated as 0 for cost estimation.
    """
    input_rate, output_rate = COST_RATES.get(model, _DEFAULT_RATE)

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
