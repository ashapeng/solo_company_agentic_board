import json

from server.discovery.lifecycle.migrate import migrate_candidates
from server.discovery.lifecycle.store import CandidateStore
from tests.test_discovery_candidate_lifecycle import _report


def test_migration_dry_run_then_backup_apply_preserves_evidence(tmp_path):
    store = CandidateStore(tmp_path)
    candidate = store.import_report(_report())[0]
    path = store._path(candidate.id)
    legacy = candidate.to_dict()
    legacy["schema_version"] = 1
    for key in ("discovery_status", "board_label", "founder_disposition", "validation_state",
                "board_rank", "board_rationale", "audit_events"):
        legacy.pop(key)
    legacy["status"] = "rejected"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    dry = migrate_candidates(tmp_path)
    assert dry.migrated == 1 and dry.backup_directory is None
    assert json.loads(path.read_text())["schema_version"] == 1

    applied = migrate_candidates(tmp_path, dry_run=False)
    restored = CandidateStore(tmp_path).get(candidate.id)
    assert applied.backup_directory and (applied.backup_directory / path.name).exists()
    assert restored.schema_version == 2 and restored.board_label.value == "reject"
    assert restored.evidence == candidate.evidence
    assert CandidateStore(tmp_path).restore(candidate.id, reason="new evidence").founder_disposition.value == "active"
