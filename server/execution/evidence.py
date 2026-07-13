"""Evidence packet persistence for post-board execution workflows."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_EVIDENCE_DIR = Path("data/evidence_packets")


@dataclass(frozen=True)
class EvidenceSource:
    title: str
    url: str
    retrieved_at: str
    claim_ids: list[str]
    publisher: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidencePacket:
    id: str
    topic: str
    claims: list[str]
    sources: list[EvidenceSource]
    created_at: str
    freshness: str = "unknown"
    warnings: list[str] = field(default_factory=list)
    discovery_candidate_id: str | None = None
    report_digest: str | None = None
    source_keys: list[str] = field(default_factory=list)
    canonical_quotes: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "claims": self.claims,
            "sources": [source.to_dict() for source in self.sources],
            "created_at": self.created_at,
            "freshness": self.freshness,
            "warnings": self.warnings,
            "discovery_candidate_id": self.discovery_candidate_id,
            "report_digest": self.report_digest,
            "source_keys": self.source_keys,
            "canonical_quotes": self.canonical_quotes,
        }


def create_evidence_packet(
    *,
    topic: str,
    claims: list[str] | None = None,
    sources: list[dict[str, Any]] | None = None,
    freshness: str = "unknown",
    warnings: list[str] | None = None,
    discovery_candidate_id: str | None = None,
    report_digest: str | None = None,
    source_keys: list[str] | None = None,
    canonical_quotes: list[dict[str, Any]] | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, Any]:
    if freshness not in {"current", "stale", "unknown"}:
        freshness = "unknown"
    packet_id = f"evidence_{time.time_ns()}"
    packet = EvidencePacket(
        id=packet_id,
        topic=topic,
        claims=claims or [],
        sources=[
            EvidenceSource(
                title=str(source.get("title") or source.get("url") or "Untitled source"),
                url=str(source.get("url") or ""),
                publisher=source.get("publisher"),
                retrieved_at=str(source.get("retrieved_at") or _utc_now()),
                claim_ids=[str(item) for item in source.get("claim_ids", [])],
            )
            for source in (sources or [])
            if isinstance(source, dict)
        ],
        created_at=_utc_now(),
        freshness=freshness,
        warnings=warnings or [],
        discovery_candidate_id=discovery_candidate_id,
        report_digest=report_digest,
        source_keys=[str(key) for key in (source_keys or [])],
        canonical_quotes=[dict(quote) for quote in (canonical_quotes or [])],
    )
    directory = evidence_dir or _EVIDENCE_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{packet_id}.json"
    content = json.dumps(packet.to_dict(), indent=2, ensure_ascii=False) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return packet.to_dict()


def get_evidence_packet(packet_id: str, *, evidence_dir: Path | None = None) -> dict[str, Any] | None:
    path = (evidence_dir or _EVIDENCE_DIR) / f"{packet_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
