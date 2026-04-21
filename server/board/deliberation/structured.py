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
    for block in _iter_json_blocks(content):
        try:
            return model.model_validate_json(block)
        except (ValidationError, ValueError):
            continue
    return None


def _iter_json_blocks(content: str):
    """Yield each JSON object candidate in content, in document order.

    First yields every ```json ... ``` (or unlabeled ``` ... ```) fenced block,
    then yields every balanced top-level {...} that starts with a '{' on its own
    boundary. Each yielded string passes json.loads; Pydantic validation happens
    in the caller.
    """
    seen_spans: list[tuple[int, int]] = []

    for match in _FENCE.finditer(content):
        span = match.span(1)
        candidate = match.group(1)
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            continue
        seen_spans.append(span)
        yield candidate

    # Fall back to raw top-level braces, skipping spans already yielded.
    i = 0
    while i < len(content):
        if content[i] == "{" and not _span_contains_index(seen_spans, i):
            depth = 0
            j = i
            while j < len(content):
                ch = content[j]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = content[i:j + 1]
                        try:
                            json.loads(candidate)
                            yield candidate
                        except json.JSONDecodeError:
                            pass
                        i = j + 1
                        break
                j += 1
            else:
                break
        else:
            i += 1


def _span_contains_index(spans: list[tuple[int, int]], idx: int) -> bool:
    return any(start <= idx < end for start, end in spans)


def _extract_json_block(content: str) -> str | None:
    """Return the first JSON object found inside ```json ... ``` or bare {...}.

    Compatibility shim — prefer _iter_json_blocks for new callers.
    """
    for block in _iter_json_blocks(content):
        return block
    return None
