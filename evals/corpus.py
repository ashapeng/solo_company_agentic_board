"""Corpus loader for the eval harness.

Each category has its own JSONL file under `evals/corpus/`. One JSON object
per line. See docs/superpowers/specs/2026-05-15-board-hardening-design.md §4.2.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

CATEGORIES: tuple[str, ...] = (
    "hallucination_planted",
    "cross_member_conflict",
    "ambiguous_query",
    "source_quality_trap",
    "sycophantic_verifier",
    "clean_baseline",
)

Tier = Literal["light", "standard", "heavy"]
_VALID_TIERS = ("light", "standard", "heavy")

_REQUIRED_FIELDS = ("id", "category", "query", "tier", "planted", "expected_outcome")

_DEFAULT_CORPUS_DIR = Path(__file__).parent / "corpus"


class CorpusError(Exception):
    """Raised on corpus loading or validation failure."""


@dataclass(frozen=True)
class EvalPrompt:
    id: str
    category: str
    query: str
    tier: str
    planted: dict[str, Any]
    expected_outcome: dict[str, Any]
    notes: str = ""

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "EvalPrompt":
        for f in _REQUIRED_FIELDS:
            if f not in row:
                raise CorpusError(f"row {row.get('id', '?')}: missing required field '{f}'")
        if row["category"] not in CATEGORIES:
            raise CorpusError(f"row {row['id']}: unknown category '{row['category']}'")
        if row["tier"] not in _VALID_TIERS:
            raise CorpusError(f"row {row['id']}: invalid tier '{row['tier']}'")
        if not isinstance(row["planted"], dict):
            raise CorpusError(f"row {row['id']}: 'planted' must be an object")
        if not isinstance(row["expected_outcome"], dict):
            raise CorpusError(f"row {row['id']}: 'expected_outcome' must be an object")
        return cls(
            id=row["id"],
            category=row["category"],
            query=row["query"],
            tier=row["tier"],
            planted=row["planted"],
            expected_outcome=row["expected_outcome"],
            notes=row.get("notes", ""),
        )


def load_category(
    category: str, *, corpus_dir: Path | None = None
) -> list[EvalPrompt]:
    """Load and validate all prompts in one category."""
    if category not in CATEGORIES:
        raise CorpusError(f"unknown category: {category}")
    base = corpus_dir or _DEFAULT_CORPUS_DIR
    path = base / f"{category}.jsonl"
    if not path.exists():
        return []
    seen: set[str] = set()
    out: list[EvalPrompt] = []
    with path.open() as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as e:
                raise CorpusError(f"{path}:{lineno} invalid JSON: {e}") from e
            prompt = EvalPrompt.from_row(row)
            if prompt.id in seen:
                raise CorpusError(f"{path}:{lineno} duplicate id '{prompt.id}'")
            seen.add(prompt.id)
            out.append(prompt)
    return out


def load_all(
    *, corpus_dir: Path | None = None
) -> list[EvalPrompt]:
    """Load all categories in spec-declared order."""
    out: list[EvalPrompt] = []
    for category in CATEGORIES:
        out.extend(load_category(category, corpus_dir=corpus_dir))
    return out
