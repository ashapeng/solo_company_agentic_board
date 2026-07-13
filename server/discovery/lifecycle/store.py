from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from server.discovery.analyze.models import TopicReport, topic_slug
from server.discovery.lifecycle.models import (
    CANDIDATE_SCHEMA_VERSION, AuditEvent, BoardLabel, Candidate, CandidateStatus, DiscoveryStatus,
    FounderDisposition, LifecycleContractError, ValidationState, allowed_transition,
)
from server.discovery.store import DiscoveryStore


INDEX_SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class ImportCandidatesResult(list[Candidate]):
    def __init__(self, candidates: list[Candidate], created: int):
        super().__init__(candidates)
        self.created = created
        self.existing = len(candidates) - created


class CandidateStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.directory = self.root / "candidates"
        self.index_path = self.directory / "index.json"

    @staticmethod
    def report_digest(report: TopicReport) -> str:
        data = report.to_dict()
        data.pop("generated_at", None)
        encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def import_key(report_digest: str, source_topic_id: str) -> str:
        return "sha256:" + hashlib.sha256(f"{report_digest}\0{source_topic_id}".encode()).hexdigest()

    def _path(self, candidate_id: str) -> Path:
        if not candidate_id.startswith("cand_") or "/" in candidate_id or "\\" in candidate_id:
            raise ValueError("invalid candidate id")
        return self.directory / f"{candidate_id}.json"

    def get(self, candidate_id: str) -> Candidate:
        path = self._path(candidate_id)
        if not path.is_file():
            raise KeyError(candidate_id)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("schema_version") == 1:
                raise LifecycleContractError("candidate schema v1 requires migrate-candidates")
            return Candidate.from_dict(raw)
        except (OSError, UnicodeError, json.JSONDecodeError, LifecycleContractError) as exc:
            raise ValueError(f"invalid candidate file {path}: {exc}") from exc

    def save(self, candidate: Candidate, *, rebuild: bool = True) -> Path:
        validated = Candidate.from_dict(candidate.to_dict())
        path = self._path(validated.id)
        DiscoveryStore._atomic_write(path, json.dumps(validated.to_dict(), indent=2, ensure_ascii=False) + "\n")
        if rebuild:
            self.rebuild_index()
        return path

    def _candidate_files(self) -> list[Path]:
        return sorted(self.directory.glob("cand_*.json")) if self.directory.exists() else []

    def rebuild_index(self) -> dict[str, Any]:
        entries = [self._index_entry(self.get(path.stem)) for path in self._candidate_files()]
        index = {"schema_version": INDEX_SCHEMA_VERSION, "generated_at": utc_now(),
                 "candidates": sorted(entries, key=lambda item: item["id"])}
        DiscoveryStore._atomic_write(self.index_path, json.dumps(index, indent=2, ensure_ascii=False) + "\n")
        return index

    def _read_index(self) -> dict[str, Any]:
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != INDEX_SCHEMA_VERSION or not isinstance(data.get("candidates"), list):
                raise ValueError("unsupported index schema")
            ids = {entry["id"] for entry in data["candidates"]}
            if ids != {path.stem for path in self._candidate_files()}:
                raise ValueError("index mismatch")
            for candidate_id in ids:
                self.get(candidate_id)
            return data
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError, KeyError, TypeError):
            return self.rebuild_index()

    @staticmethod
    def _index_entry(candidate: Candidate) -> dict[str, Any]:
        return {
            "id": candidate.id, "title": candidate.title, "title_slug": candidate.title_slug,
            "report_week": candidate.report_week, "discovery_status": candidate.discovery_status.value,
            "board_label": candidate.board_label.value if candidate.board_label else None,
            "founder_disposition": candidate.founder_disposition.value,
            "validation_state": candidate.validation_state.value, "board_rank": candidate.board_rank,
            "signal_strength": candidate.signal_strength, "updated_at": candidate.updated_at,
            "import_key": candidate.provenance["import_key"],
        }

    def list(self, *, discovery_status: DiscoveryStatus | str | None = None,
             status: str | None = None, week: str | None = None,
             founder_disposition: FounderDisposition | str | None = None) -> list[Candidate]:
        # status is a temporary read-only CLI compatibility filter.
        wanted = DiscoveryStatus(discovery_status) if discovery_status is not None else None
        disposition = FounderDisposition(founder_disposition) if founder_disposition is not None else None
        candidates = [self.get(entry["id"]) for entry in self._read_index()["candidates"]]
        return [item for item in candidates if
                (wanted is None or item.discovery_status is wanted) and
                (status is None or item.status.value == status) and
                (week is None or item.report_week == week) and
                (disposition is None or item.founder_disposition is disposition)]

    def update(self, candidate_id: str, *, actor: str, reason: str,
               related_session_id: str | None = None,
               related_experiment_id: str | None = None, **changes: Any) -> Candidate:
        allowed = {"discovery_status", "board_label", "founder_disposition", "validation_state",
                   "board_rank", "board_rationale", "promotion", "board_sessions"}
        unknown = changes.keys() - allowed
        if unknown:
            raise ValueError(f"unsupported candidate field: {sorted(unknown)[0]}")
        candidate = self.get(candidate_id)
        now = utc_now()
        events = list(candidate.audit_events)
        normalized = dict(changes)
        enum_fields = {"discovery_status": DiscoveryStatus, "board_label": BoardLabel,
                       "founder_disposition": FounderDisposition, "validation_state": ValidationState}
        for name, enum_type in enum_fields.items():
            if name in normalized and normalized[name] is not None:
                normalized[name] = enum_type(normalized[name])
        for field_name, new_value in normalized.items():
            previous = getattr(candidate, field_name)
            if previous == new_value:
                continue
            events.append(AuditEvent(
                actor=actor, field=field_name,
                previous_value=previous.value if isinstance(previous, (DiscoveryStatus, BoardLabel, FounderDisposition, ValidationState)) else previous,
                new_value=new_value.value if isinstance(new_value, (DiscoveryStatus, BoardLabel, FounderDisposition, ValidationState)) else new_value,
                reason=reason, occurred_at=now, related_session_id=related_session_id,
                related_experiment_id=related_experiment_id,
            ))
        updated = replace(candidate, **normalized, audit_events=events, updated_at=now)
        self.save(updated)
        return updated

    def transition(self, candidate_id: str, target: CandidateStatus | str,
                   *, decision: dict[str, Any] | None = None) -> Candidate:
        """Compatibility-only legacy transition used by existing local callers."""
        candidate = self.get(candidate_id)
        target = CandidateStatus(target)
        if target is candidate.status:
            return candidate
        if not allowed_transition(candidate.status, target):
            raise ValueError(f"invalid candidate transition: {candidate.status.value} -> {target.value}")
        dimensions = {
            CandidateStatus.NEW: (DiscoveryStatus.NEW, None, ValidationState.NOT_SELECTED),
            CandidateStatus.SHORTLISTED: (DiscoveryStatus.READY_FOR_BOARD, None, ValidationState.NOT_SELECTED),
            CandidateStatus.REJECTED: (DiscoveryStatus.REVIEWED, BoardLabel.REJECT, ValidationState.REJECTED),
            CandidateStatus.PROMOTED: (DiscoveryStatus.REVIEWED, BoardLabel.PRIORITIZE, ValidationState.QUEUED),
            CandidateStatus.BOARD_STARTED: (DiscoveryStatus.REVIEWED, BoardLabel.PRIORITIZE, ValidationState.VALIDATING),
        }
        discovery, label, validation = dimensions[target]
        decisions = list(candidate.founder_decisions)
        if decision is not None:
            decisions.append(dict(decision))
        now = utc_now()
        updated = replace(candidate, status=target, discovery_status=discovery,
                          board_label=label, validation_state=validation,
                          founder_decisions=decisions, updated_at=now,
                          audit_events=[*candidate.audit_events, AuditEvent(
                              actor="compatibility", field="status", previous_value=candidate.status.value,
                              new_value=target.value, reason="legacy transition", occurred_at=now)])
        self.save(updated)
        return updated

    def dispose(self, candidate_id: str, *, reason: str, actor: str = "founder") -> Candidate:
        return self.update(candidate_id, actor=actor, reason=reason,
                           founder_disposition=FounderDisposition.DISPOSED)

    def restore(self, candidate_id: str, *, reason: str, actor: str = "founder") -> Candidate:
        return self.update(candidate_id, actor=actor, reason=reason,
                           founder_disposition=FounderDisposition.ACTIVE)

    def import_report(self, report: TopicReport) -> ImportCandidatesResult:
        digest = self.report_digest(report)
        existing = {item.provenance.get("import_key"): item for item in self.list()}
        imported: list[Candidate] = []
        created = 0
        now = utc_now()
        for topic in report.topics:
            key = self.import_key(digest, topic.id)
            if key in existing:
                imported.append(existing[key]); continue
            candidate = Candidate(
                schema_version=CANDIDATE_SCHEMA_VERSION, id=f"cand_{uuid4().hex}",
                title_slug=topic_slug(topic.title) or "untitled", report_week=report.week,
                report_digest=digest, producer_run_id=report.producer.run_id, title=topic.title,
                summary=topic.summary, audience=topic.who, pain_class=topic.pain_class,
                signal_strength=topic.signal_strength, engagement_score=topic.engagement_score,
                evidence=topic.evidence, resources=topic.resources,
                status=CandidateStatus.SHORTLISTED,
                discovery_status=DiscoveryStatus.READY_FOR_BOARD,
                provenance={"import_key": key, "source_topic_id": topic.id,
                            "bundle_digest": report.bundle_digest,
                            "analyzed_report": f"analyzed/{report.week}/topics.json"},
                audit_events=[AuditEvent(actor="system", field="discovery_status",
                                         previous_value=None, new_value="ready_for_board",
                                         reason="validated weekly report import", occurred_at=now)],
                created_at=now, updated_at=now,
            )
            self.save(candidate, rebuild=False)
            imported.append(candidate); existing[key] = candidate; created += 1
        self.rebuild_index()
        return ImportCandidatesResult(imported, created)
