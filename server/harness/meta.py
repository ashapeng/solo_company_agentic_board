# server/harness/meta.py
"""Per-tuner accuracy = applied-and-not-reverted / applied."""

from __future__ import annotations

import json
from pathlib import Path


def tuner_accuracy(db_path: Path | None = None) -> dict[str, dict[str, float]]:
    """Return per-tuner counts and accuracy from harness_config_activations."""
    from .ledger import _connect

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT snapshot, reverted_at FROM harness_config_activations"
        ).fetchall()
    finally:
        conn.close()

    totals: dict[str, dict[str, int]] = {}
    for snapshot_json, reverted_at in rows:
        try:
            snapshot = json.loads(snapshot_json or "{}")
        except json.JSONDecodeError:
            continue
        for tuner_name, report in snapshot.items():
            if not isinstance(report, dict):
                continue
            if not report.get("changes"):
                continue
            stats = totals.setdefault(tuner_name, {"applied": 0, "reverted": 0})
            stats["applied"] += 1
            if reverted_at:
                stats["reverted"] += 1

    return {
        name: {
            "applied": v["applied"],
            "reverted": v["reverted"],
            "accuracy": (
                0.0
                if v["applied"] == 0
                else round(1.0 - (v["reverted"] / v["applied"]), 3)
            ),
        }
        for name, v in totals.items()
    }
