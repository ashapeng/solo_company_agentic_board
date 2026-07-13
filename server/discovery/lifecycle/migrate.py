"""Deterministic, backup-first migration of durable candidate files to schema v2."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.discovery.lifecycle.models import (
    CANDIDATE_SCHEMA_VERSION, AuditEvent, BoardLabel, Candidate, DiscoveryStatus,
    FounderDisposition, LifecycleContractError, ValidationState,
)
from server.discovery.store import DiscoveryStore


@dataclass(frozen=True)
class MigrationResult:
    inspected: int
    migrated: int
    unchanged: int
    backup_directory: Path | None
    dry_run: bool


def migrate_candidates(root: Path, *, dry_run: bool = True) -> MigrationResult:
    directory = Path(root) / "candidates"
    paths = sorted(directory.glob("cand_*.json")) if directory.exists() else []
    converted: list[tuple[Path, Candidate]] = []
    unchanged = 0
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise LifecycleContractError(f"cannot migrate {path}: {exc}") from exc
        version = raw.get("schema_version") if isinstance(raw, dict) else None
        if version == CANDIDATE_SCHEMA_VERSION:
            Candidate.from_dict(raw)
            unchanged += 1
        elif version == 1:
            converted.append((path, migrate_v1_candidate(raw)))
        else:
            raise LifecycleContractError(f"cannot migrate {path}: unsupported schema {version!r}")
    if dry_run or not converted:
        return MigrationResult(len(paths), len(converted), unchanged, None, dry_run)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = directory / "backups" / f"schema-v1-{stamp}"
    backup.mkdir(parents=True, exist_ok=False)
    for path, _ in converted:
        shutil.copy2(path, backup / path.name)
    if (directory / "index.json").exists():
        shutil.copy2(directory / "index.json", backup / "index.json")
    for path, candidate in converted:
        DiscoveryStore._atomic_write(path, json.dumps(candidate.to_dict(), indent=2, ensure_ascii=False) + "\n")
    from server.discovery.lifecycle.store import CandidateStore
    CandidateStore(root).rebuild_index()
    return MigrationResult(len(paths), len(converted), unchanged, backup, False)


def migrate_v1_candidate(raw: dict[str, Any]) -> Candidate:
    status = raw.get("status")
    promotion = raw.get("promotion")
    sessions = raw.get("board_sessions") or []
    mapping = {
        "new": (DiscoveryStatus.READY_FOR_BOARD, None, ValidationState.NOT_SELECTED),
        "shortlisted": (DiscoveryStatus.READY_FOR_BOARD, None, ValidationState.NOT_SELECTED),
        "rejected": (DiscoveryStatus.REVIEWED, BoardLabel.REJECT, ValidationState.REJECTED),
        "promoted": (DiscoveryStatus.REVIEWED, BoardLabel.PRIORITIZE, ValidationState.QUEUED),
        "board_started": (DiscoveryStatus.REVIEWED, BoardLabel.PRIORITIZE, ValidationState.VALIDATING),
    }
    if status not in mapping:
        raise LifecycleContractError(f"ambiguous legacy candidate status: {status!r}")
    if status in {"promoted", "board_started"} and not isinstance(promotion, dict):
        raise LifecycleContractError(f"legacy {status} candidate is ambiguous without promotion")
    if status == "board_started" and not sessions:
        raise LifecycleContractError("legacy board_started candidate is ambiguous without board session")
    discovery, label, validation = mapping[status]
    occurred = str(raw.get("updated_at") or raw.get("created_at") or "").strip()
    if not occurred:
        raise LifecycleContractError("legacy candidate timestamps are required")
    data = dict(raw)
    data.update(
        schema_version=CANDIDATE_SCHEMA_VERSION,
        status=status,
        discovery_status=discovery.value,
        board_label=label.value if label else None,
        founder_disposition=FounderDisposition.ACTIVE.value,
        validation_state=validation.value,
        board_rank=None,
        board_rationale=None,
        audit_events=[AuditEvent(actor="migration", field="legacy_status",
                                 previous_value=status, new_value=discovery.value,
                                 reason="deterministic schema v1 to v2 migration",
                                 occurred_at=occurred).__dict__],
    )
    return Candidate.from_dict(data)
