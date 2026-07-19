from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ACTIVE_EXPERIMENT_STATUSES, TRANSITIONS, ExperimentStatus, ValidationExperiment


DEFAULT_DB_PATH = Path("data/harness_ledger.db")
SCHEMA = """
CREATE TABLE IF NOT EXISTS validation_experiments (
 experiment_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, portfolio_review_id TEXT NOT NULL,
 board_session_id TEXT NOT NULL, venture_id TEXT NOT NULL, initiative_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, status TEXT NOT NULL, review_at TEXT NOT NULL, expires_at TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(candidate_id, portfolio_review_id)
);
CREATE INDEX IF NOT EXISTS idx_validation_experiments_status ON validation_experiments(status);
CREATE TABLE IF NOT EXISTS validation_experiment_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT, experiment_id TEXT NOT NULL, actor TEXT NOT NULL,
 previous_status TEXT, new_status TEXT NOT NULL, reason TEXT NOT NULL, occurred_at TEXT NOT NULL
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or DEFAULT_DB_PATH)

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        return conn

    def create(self, experiment: ValidationExperiment, *, actor: str = "system") -> ValidationExperiment:
        validated = ValidationExperiment.from_dict(experiment.to_dict())
        conn = self._connect()
        try:
            row = conn.execute("SELECT payload_json FROM validation_experiments WHERE candidate_id=? AND portfolio_review_id=?",
                               (validated.candidate_id, validated.portfolio_review_id)).fetchone()
            if row:
                return ValidationExperiment.from_dict(json.loads(row["payload_json"]))
            payload = json.dumps(validated.to_dict(), ensure_ascii=False, sort_keys=True)
            conn.execute("INSERT INTO validation_experiments VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                validated.id, validated.candidate_id, validated.portfolio_review_id,
                validated.board_session_id, validated.venture_id, validated.initiative_id, payload,
                validated.status.value, validated.review_at, validated.expires_at,
                validated.created_at, validated.updated_at,
            ))
            conn.execute("INSERT INTO validation_experiment_events (experiment_id,actor,previous_status,new_status,reason,occurred_at) VALUES (?,?,?,?,?,?)",
                         (validated.id, actor, None, validated.status.value, "experiment created", validated.created_at))
            conn.commit()
            return validated
        finally:
            conn.close()

    def get(self, experiment_id: str) -> ValidationExperiment | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT payload_json FROM validation_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
            return ValidationExperiment.from_dict(json.loads(row["payload_json"])) if row else None
        finally:
            conn.close()

    def get_for_candidate_review(self, candidate_id: str, portfolio_review_id: str) -> ValidationExperiment | None:
        conn = self._connect()
        try:
            row = conn.execute("SELECT payload_json FROM validation_experiments WHERE candidate_id=? AND portfolio_review_id=?",
                               (candidate_id, portfolio_review_id)).fetchone()
            return ValidationExperiment.from_dict(json.loads(row["payload_json"])) if row else None
        finally:
            conn.close()

    def list(self, *, statuses: set[ExperimentStatus] | None = None) -> list[ValidationExperiment]:
        conn = self._connect()
        try:
            rows = conn.execute("SELECT payload_json FROM validation_experiments ORDER BY created_at, experiment_id").fetchall()
        finally:
            conn.close()
        values = [ValidationExperiment.from_dict(json.loads(row["payload_json"])) for row in rows]
        return [item for item in values if statuses is None or item.status in statuses]

    def active_count(self) -> int:
        return len(self.list(statuses=set(ACTIVE_EXPERIMENT_STATUSES)))

    def available_capacity(self, maximum: int = 5) -> int:
        if maximum < 1 or maximum > 5:
            raise ValueError("maximum active experiments must be between 1 and 5")
        return max(0, maximum - self.active_count())

    def transition(self, experiment_id: str, target: ExperimentStatus | str, *, actor: str,
                   reason: str, deployment: dict[str, Any] | None = None) -> ValidationExperiment:
        current = self.get(experiment_id)
        if current is None:
            raise KeyError(experiment_id)
        target = ExperimentStatus(target)
        if target is current.status:
            return current
        if target not in TRANSITIONS[current.status]:
            raise ValueError(f"invalid experiment transition: {current.status.value} -> {target.value}")
        if target is ExperimentStatus.EXTENDED and current.extension_count >= 1:
            raise ValueError("experiment can only be extended once")
        now = utc_now()
        decision_history = list(current.decision_history)
        if current.status is ExperimentStatus.REVIEW_DUE:
            decision_history.append({"outcome": target.value, "actor": actor, "reason": reason, "occurred_at": now})
        updated = replace(current, status=target, updated_at=now,
                          landing_page_deployment=deployment if deployment is not None else current.landing_page_deployment,
                          extension_count=current.extension_count + (1 if target is ExperimentStatus.EXTENDED else 0),
                          review_at=current.expires_at if target is ExperimentStatus.EXTENDED else current.review_at,
                          decision_history=decision_history)
        conn = self._connect()
        try:
            payload = json.dumps(updated.to_dict(), ensure_ascii=False, sort_keys=True)
            conn.execute("UPDATE validation_experiments SET payload_json=?,status=?,review_at=?,updated_at=? WHERE experiment_id=?",
                         (payload, target.value, updated.review_at, now, experiment_id))
            conn.execute("INSERT INTO validation_experiment_events (experiment_id,actor,previous_status,new_status,reason,occurred_at) VALUES (?,?,?,?,?,?)",
                         (experiment_id, actor, current.status.value, target.value, reason, now))
            conn.commit()
        finally:
            conn.close()
        return updated

    def due_reviews(self, at: str | None = None) -> list[ValidationExperiment]:
        cutoff = at or utc_now()
        return [item for item in self.list(statuses=set(ACTIVE_EXPERIMENT_STATUSES))
                if item.review_at <= cutoff]

    def events(self, experiment_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            return [dict(row) for row in conn.execute(
                "SELECT actor,previous_status,new_status,reason,occurred_at FROM validation_experiment_events WHERE experiment_id=? ORDER BY event_id",
                (experiment_id,)).fetchall()]
        finally:
            conn.close()
