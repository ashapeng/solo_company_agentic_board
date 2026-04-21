# server/board/deliberation/structured.py
"""Pydantic schemas for Stage 1 / Stage 2 structured output.

Provides:
  - Stage1Response, Stage2Response, Risk models
  - parse_stage1 / parse_stage2 — best-effort JSON extraction from a
    markdown body that may or may not contain a ```json fenced block.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Risk(BaseModel):
    severity: Literal["Critical", "High", "Medium", "Low"]
    description: str


class Stage1Response(BaseModel):
    confidence: Literal["High", "Medium", "Low"]
    tldr: str
    analysis: str
    recommendation: str
    risks: list[Risk] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Stage2Response(BaseModel):
    confidence: Literal["High", "Medium", "Low"]
    updated_position: str
    peer_challenges: list[str] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_stage1(content: str) -> Stage1Response | None:
    return _parse(content, Stage1Response)


def parse_stage2(content: str) -> Stage2Response | None:
    return _parse(content, Stage2Response)


def _parse(content: str, model: type[BaseModel]):
    block = _extract_json_block(content)
    if not block:
        return None
    try:
        return model.model_validate_json(block)
    except (ValidationError, ValueError):
        return None


def _extract_json_block(content: str) -> str | None:
    """Return the first JSON object found inside ```json ... ``` or bare {...}."""
    match = _FENCE.search(content)
    if match:
        return match.group(1)
    # Fallback: first top-level { ... } JSON object.
    start = content.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = content[start:i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None
    return None
