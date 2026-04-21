# server/harness/shadow.py
"""Post-apply regression watcher for harness reviews.

Reads the baseline mean verification score (sessions preceding activation)
and a recent window (sessions after activation). If the delta regresses by
more than a threshold, reverts the activation and restores the previous
harness config snapshot.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from statistics import mean

logger = logging.getLogger(__name__)


def watch_after_apply(
    review_id: str,
    *,
    window: int = 10,
    baseline: int = 20,
    regression_threshold: float = 1.0,
    db_path: Path | None = None,
) -> dict:
    """Observe N sessions after activation; auto-revert on regression.

    Returns a dict describing baseline/current/delta and whether a revert occurred.
    """
    if os.getenv("AGENTIC_BOARD_SHADOW_DISABLED") == "1":
        return {"reverted": False, "reason": "shadow disabled via env"}

    from .ledger import _connect, revert_activation

    conn = _connect(db_path)
    try:
        act = conn.execute(
            "SELECT activated_at FROM harness_config_activations WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        if not act:
            return {"reverted": False, "reason": "activation not found"}

        # Window rows: sessions recorded after this review was activated,
        # identified via the applied_review_id column set by record_session.
        window_rows = conn.execute(
            "SELECT verification_score FROM session_outcomes "
            "WHERE applied_review_id = ? AND verification_score IS NOT NULL "
            "ORDER BY rowid ASC LIMIT ?",
            (review_id, window),
        ).fetchall()

        # Baseline rows: sessions recorded before this review was activated.
        baseline_rows = conn.execute(
            "SELECT verification_score FROM session_outcomes "
            "WHERE (applied_review_id IS NULL OR applied_review_id != ?) "
            "AND verification_score IS NOT NULL "
            "ORDER BY rowid DESC LIMIT ?",
            (review_id, baseline),
        ).fetchall()
    finally:
        conn.close()

    if len(baseline_rows) < 3 or len(window_rows) < window:
        return {
            "reverted": False,
            "reason": "insufficient samples",
            "baseline_n": len(baseline_rows),
            "window_n": len(window_rows),
        }

    baseline_mean = mean(r[0] for r in baseline_rows)
    window_mean = mean(r[0] for r in window_rows)
    delta = window_mean - baseline_mean

    if delta >= -regression_threshold:
        return {
            "reverted": False,
            "baseline_mean": baseline_mean,
            "window_mean": window_mean,
            "delta": delta,
        }

    previous_snapshot = revert_activation(
        review_id,
        reason=f"regression delta={delta:.2f}",
        db_path=db_path,
    )
    if previous_snapshot is not None:
        try:
            _restore_from_snapshot(previous_snapshot)
        except Exception:
            logger.exception("Failed to restore previous harness config snapshot")
            return {
                "reverted": False,
                "reason": "restore failed",
                "baseline_mean": baseline_mean,
                "window_mean": window_mean,
                "delta": delta,
            }
    return {
        "reverted": True,
        "reason": f"regression delta={delta:.2f}",
        "baseline_mean": baseline_mean,
        "window_mean": window_mean,
        "delta": delta,
    }


def _restore_from_snapshot(snapshot: dict) -> None:
    """Overwrite live HarnessConfig fields from a snapshot dict."""
    from .config import HarnessConfig, save_config

    restored = HarnessConfig()
    for key, value in (snapshot or {}).items():
        if hasattr(restored, key):
            try:
                setattr(restored, key, value)
            except Exception:
                logger.warning("Skipped unsettable field during restore: %s", key)
    save_config(restored)
