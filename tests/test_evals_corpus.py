"""Corpus loader tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.corpus import (
    CATEGORIES,
    EvalPrompt,
    CorpusError,
    load_category,
    load_all,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_categories_match_spec():
    assert CATEGORIES == (
        "hallucination_planted",
        "cross_member_conflict",
        "ambiguous_query",
        "source_quality_trap",
        "sycophantic_verifier",
        "clean_baseline",
    )


def test_load_category_returns_prompts(tmp_path):
    corpus_dir = tmp_path / "corpus"
    rows = [
        {
            "id": "ambig-001",
            "category": "ambiguous_query",
            "query": "How should we grow?",
            "tier": "heavy",
            "planted": {
                "kind": "underspecified",
                "expected_signal": "intake_clarification_required",
                "ground_truth_note": "No domain specified.",
            },
            "expected_outcome": {"clarification_required": True},
        }
    ]
    _write_jsonl(corpus_dir / "ambiguous_query.jsonl", rows)

    prompts = load_category("ambiguous_query", corpus_dir=corpus_dir)

    assert len(prompts) == 1
    assert isinstance(prompts[0], EvalPrompt)
    assert prompts[0].id == "ambig-001"
    assert prompts[0].category == "ambiguous_query"
    assert prompts[0].tier == "heavy"
    assert prompts[0].expected_outcome == {"clarification_required": True}


def test_load_all_orders_by_category(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_jsonl(
        corpus_dir / "ambiguous_query.jsonl",
        [
            {
                "id": "ambig-001",
                "category": "ambiguous_query",
                "query": "?",
                "tier": "heavy",
                "planted": {"kind": "x", "expected_signal": "y", "ground_truth_note": "z"},
                "expected_outcome": {"clarification_required": True},
            }
        ],
    )
    _write_jsonl(
        corpus_dir / "clean_baseline.jsonl",
        [
            {
                "id": "clean-001",
                "category": "clean_baseline",
                "query": "Explain CAP theorem.",
                "tier": "heavy",
                "planted": {"kind": "n/a", "expected_signal": "no_signal", "ground_truth_note": "Standard textbook."},
                "expected_outcome": {"verifier_passed": True, "contradiction_surfaced": False},
            }
        ],
    )

    prompts = load_all(corpus_dir=corpus_dir)

    assert [p.id for p in prompts] == ["ambig-001", "clean-001"]


def test_load_all_ignores_unknown_category_files(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_jsonl(
        corpus_dir / "nonsense.jsonl",
        [{"id": "x", "category": "nonsense", "query": "?", "tier": "heavy",
          "planted": {}, "expected_outcome": {}}],
    )
    # load_all should silently skip files not named after a known category
    assert load_all(corpus_dir=corpus_dir) == []


def test_rejects_missing_required_field(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_jsonl(
        corpus_dir / "ambiguous_query.jsonl",
        [{"id": "ambig-001", "category": "ambiguous_query"}],  # missing query, tier, etc.
    )
    with pytest.raises(CorpusError, match="missing required field"):
        load_category("ambiguous_query", corpus_dir=corpus_dir)


def test_rejects_unknown_tier(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_jsonl(
        corpus_dir / "ambiguous_query.jsonl",
        [{
            "id": "x", "category": "ambiguous_query", "query": "?", "tier": "ultra",
            "planted": {"kind": "x", "expected_signal": "y", "ground_truth_note": "z"},
            "expected_outcome": {"clarification_required": True},
        }],
    )
    with pytest.raises(CorpusError, match="tier"):
        load_category("ambiguous_query", corpus_dir=corpus_dir)


def test_rejects_id_collision(tmp_path):
    corpus_dir = tmp_path / "corpus"
    _write_jsonl(
        corpus_dir / "ambiguous_query.jsonl",
        [
            {"id": "ambig-001", "category": "ambiguous_query", "query": "a", "tier": "heavy",
             "planted": {"kind": "x", "expected_signal": "y", "ground_truth_note": "z"},
             "expected_outcome": {"clarification_required": True}},
            {"id": "ambig-001", "category": "ambiguous_query", "query": "b", "tier": "heavy",
             "planted": {"kind": "x", "expected_signal": "y", "ground_truth_note": "z"},
             "expected_outcome": {"clarification_required": True}},
        ],
    )
    with pytest.raises(CorpusError, match="duplicate id"):
        load_category("ambiguous_query", corpus_dir=corpus_dir)


from evals.corpus import _DEFAULT_CORPUS_DIR


def test_corpus_completeness_matches_spec():
    """Spec §4.3 mandates exact counts per category."""
    expected_counts = {
        "hallucination_planted": 8,
        "cross_member_conflict": 5,
        "ambiguous_query": 4,
        "source_quality_trap": 4,
        "sycophantic_verifier": 2,
        "clean_baseline": 2,
    }
    for category, expected in expected_counts.items():
        prompts = load_category(category, corpus_dir=_DEFAULT_CORPUS_DIR)
        assert len(prompts) == expected, (
            f"{category}: expected {expected} prompts, got {len(prompts)}"
        )


def test_corpus_total_is_25():
    prompts = load_all(corpus_dir=_DEFAULT_CORPUS_DIR)
    assert len(prompts) == 25


def test_corpus_ids_globally_unique():
    prompts = load_all(corpus_dir=_DEFAULT_CORPUS_DIR)
    ids = [p.id for p in prompts]
    assert len(ids) == len(set(ids))
