"""Render a board result into channel-friendly Markdown.

Channels speak short, human messages. This module pulls a stable, minimal
view (executive summary + next steps + decision text) out of whatever the
deliberation backend produced — a ``BoardSession``, a dict, or a
``BoardDecisionProjection`` — and never raises: if the shape is unexpected it
falls back to a truncated ``str(result)``.
"""

from __future__ import annotations

from typing import Any

_MAX_FALLBACK = 2000


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        items = [_as_text(item) for item in value]
        return "\n".join(f"- {item}" for item in items if item)
    return str(value).strip()


def _get(obj: Any, name: str) -> Any:
    """Read ``name`` from a dict or an attribute-bearing object."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _coerce_decision(result: Any) -> dict[str, Any] | None:
    """Best-effort extraction of a decision-like mapping from ``result``."""
    # 1. A BoardDecisionProjection (has to_dict).
    to_dict = getattr(result, "to_dict", None)
    if callable(to_dict) and not isinstance(result, dict):
        try:
            maybe = to_dict()
            if isinstance(maybe, dict) and "executive_summary" in maybe:
                return maybe
        except Exception:
            pass

    # 2. A dict that already looks like a decision.
    if isinstance(result, dict):
        if "executive_summary" in result or "next_steps" in result:
            return result
        nested = result.get("decision")
        if isinstance(nested, dict):
            return nested

    # 3. A BoardSession-like object: prefer .decision, fall back to synthesis.
    decision = _get(result, "decision")
    if isinstance(decision, dict):
        return decision

    synthesis = _get(result, "stage3_synthesis")
    content = _get(synthesis, "content") if synthesis is not None else None
    if isinstance(content, str) and content.strip():
        try:
            from server.board.projection import project_board_decision

            projected = project_board_decision(content)
            if isinstance(projected, dict):
                return projected
        except Exception:
            return {"executive_summary": content.strip()}

    return None


def render_brief(result: Any) -> str:
    """Format a board result as channel-friendly Markdown. Never raises."""
    try:
        decision = _coerce_decision(result)
        if not decision:
            return str(result)[:_MAX_FALLBACK]

        parts: list[str] = []

        summary = _as_text(decision.get("executive_summary"))
        if summary:
            parts.append(f"*Board Decision*\n\n{summary}")

        direction = _as_text(decision.get("strategic_direction"))
        if direction and not summary:
            parts.append(f"*Board Decision*\n\n{direction}")

        next_steps = _as_text(decision.get("next_steps"))
        if next_steps:
            parts.append(f"*Next Steps*\n{next_steps}")

        if not parts:
            return str(result)[:_MAX_FALLBACK]

        return "\n\n".join(parts)
    except Exception:
        try:
            return str(result)[:_MAX_FALLBACK]
        except Exception:
            return "(unrenderable board result)"
