"""Phase D harness evolution: routing accuracy and compaction tracking."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from server.board.config import BoardMember, get_board_members
from server.board.deliberation.compaction import extract_stage1_compaction_elements

from .config import (
    HarnessConfig,
    load_config,
    resolve_stage1_compaction_policy,
    save_config,
)
from .ledger import query_outcomes


DEFAULT_SESSIONS_DIR = Path("data/sessions")
MIN_PHASE_D_SESSIONS_PER_QUERY_TYPE = 50
MIN_ROUTED_COUNT_PER_MEMBER = 10
ROUTING_UNUSED_CITATION_RATE = 0.10
COMPACTION_DROP_USAGE_RATE = 0.05
COMPACTION_DETAIL_USAGE_RATE = 0.60
CHAIRPERSON_ID = "chairperson"
_TUNABLE_STAGE1_SECTIONS = ["tldr", "recommendation", "top_risk"]
_STOPWORDS = {
    "about", "after", "again", "because", "before", "being", "between",
    "could", "doing", "from", "have", "impact", "into", "must", "only",
    "probability", "risk", "should", "that", "their", "there", "these",
    "this", "with", "would", "your",
}


@dataclass(frozen=True)
class RoutingChange:
    query_type: str
    member_id: str
    routed_count: int
    cited_count: int
    citation_rate: float
    action: str


@dataclass(frozen=True)
class CompactionChange:
    query_type: str
    section: str
    observed_count: int
    used_count: int
    usage_rate: float
    action: str


@dataclass(frozen=True)
class PhaseDTuningReport:
    analyzed_sessions: int
    examined_query_types: int
    eligible_query_types: int
    routing_changes: list[RoutingChange]
    compaction_changes: list[CompactionChange]
    saved: bool
    dry_run: bool
    config_version: int

    def to_dict(self) -> dict:
        return {
            "analyzed_sessions": self.analyzed_sessions,
            "examined_query_types": self.examined_query_types,
            "eligible_query_types": self.eligible_query_types,
            "routing_changes": [asdict(change) for change in self.routing_changes],
            "compaction_changes": [asdict(change) for change in self.compaction_changes],
            "saved": self.saved,
            "dry_run": self.dry_run,
            "config_version": self.config_version,
        }


def tune_routing_and_compaction(
    *,
    db_path: Path | None = None,
    config_path: Path | None = None,
    sessions_dir: Path | None = None,
    min_sessions: int = MIN_PHASE_D_SESSIONS_PER_QUERY_TYPE,
    dry_run: bool = False,
) -> PhaseDTuningReport:
    """Tune routing suppression and Stage 1 compaction policy from saved sessions."""
    config = load_config(config_path)
    working_config = deepcopy(config)
    session_root = sessions_dir or DEFAULT_SESSIONS_DIR
    outcomes = query_outcomes(db_path=db_path)
    observations = _load_phase_d_observations(outcomes, session_root)

    routing_changes = _apply_routing_tuning(
        working_config,
        observations,
        min_sessions=min_sessions,
    )
    compaction_changes = _apply_compaction_tuning(
        working_config,
        observations,
        min_sessions=min_sessions,
    )
    changes = routing_changes or compaction_changes

    saved = False
    if changes and not dry_run:
        save_config(working_config, config_path)
        saved = True

    eligible_query_types = _eligible_query_type_count(observations, min_sessions=min_sessions)
    return PhaseDTuningReport(
        analyzed_sessions=len(observations),
        examined_query_types=len({obs["query_type"] for obs in observations}),
        eligible_query_types=eligible_query_types,
        routing_changes=routing_changes,
        compaction_changes=compaction_changes,
        saved=saved,
        dry_run=dry_run,
        config_version=working_config.version,
    )


def extract_cited_member_ids(
    synthesis: str,
    *,
    members: list[BoardMember] | None = None,
) -> set[str]:
    """Extract board member IDs explicitly cited in a chairman synthesis."""
    if not synthesis:
        return set()

    member_list = members or get_board_members()
    cited: set[str] = set()
    normalized = synthesis.lower()

    for member in member_list:
        for alias in _member_aliases(member):
            pattern = rf"(?<![a-z0-9_]){re.escape(alias.lower())}(?![a-z0-9_])"
            if re.search(pattern, normalized):
                cited.add(member.id)
                break

    return cited


def _load_phase_d_observations(
    outcomes: list[dict[str, Any]],
    sessions_dir: Path,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for row in outcomes:
        query_type = row.get("query_type")
        session_id = row.get("session_id")
        if not query_type or not session_id:
            continue

        session = _load_session(sessions_dir, str(session_id))
        if not session:
            continue

        synthesis = _stage3_content(session)
        if not synthesis:
            continue

        observations.append({
            "session_id": str(session_id),
            "query_type": str(query_type),
            "members_routed": _members_routed(row),
            "cited_member_ids": extract_cited_member_ids(synthesis),
            "stage1": session.get("stage1") or [],
            "synthesis": synthesis,
        })
    return observations


def _apply_routing_tuning(
    config: HarnessConfig,
    observations: list[dict[str, Any]],
    *,
    min_sessions: int,
) -> list[RoutingChange]:
    by_query = _group_observations_by_query_type(observations)
    changes: list[RoutingChange] = []

    for query_type, rows in sorted(by_query.items()):
        if len(rows) < min_sessions:
            continue
        if not any(_non_chair_citations(row) for row in rows):
            continue

        stats: dict[str, dict[str, int]] = defaultdict(lambda: {"routed": 0, "cited": 0})
        for row in rows:
            routed = [mid for mid in row["members_routed"] if mid != CHAIRPERSON_ID]
            cited = set(row["cited_member_ids"])
            for member_id in routed:
                stats[member_id]["routed"] += 1
                if member_id in cited:
                    stats[member_id]["cited"] += 1

        suppressions = set(_current_suppressed_members(config, query_type))
        for member_id, counts in sorted(stats.items()):
            routed_count = counts["routed"]
            cited_count = counts["cited"]
            if routed_count < MIN_ROUTED_COUNT_PER_MEMBER:
                continue
            citation_rate = cited_count / routed_count
            if citation_rate > ROUTING_UNUSED_CITATION_RATE:
                continue
            if member_id in suppressions:
                continue

            suppressions.add(member_id)
            changes.append(RoutingChange(
                query_type=query_type,
                member_id=member_id,
                routed_count=routed_count,
                cited_count=cited_count,
                citation_rate=round(citation_rate, 4),
                action="suppress",
            ))

        if suppressions:
            _set_suppressed_members(config, query_type, sorted(suppressions))

    return changes


def _apply_compaction_tuning(
    config: HarnessConfig,
    observations: list[dict[str, Any]],
    *,
    min_sessions: int,
) -> list[CompactionChange]:
    by_query = _group_observations_by_query_type(observations)
    changes: list[CompactionChange] = []

    for query_type, rows in sorted(by_query.items()):
        if len(rows) < min_sessions:
            continue

        observed: dict[str, int] = defaultdict(int)
        used: dict[str, int] = defaultdict(int)

        for row in rows:
            synthesis = row["synthesis"]
            for stage1 in row["stage1"]:
                if not isinstance(stage1, dict):
                    continue
                elements = extract_stage1_compaction_elements(stage1.get("content", ""))
                for section in _TUNABLE_STAGE1_SECTIONS:
                    text = elements.get(section)
                    if not text:
                        continue
                    observed[section] += 1
                    if _section_used_in_synthesis(text, synthesis):
                        used[section] += 1

        if not observed:
            continue

        proposed_sections = ["confidence"]
        proposed_detail_sections: list[str] = []
        candidate_changes: list[CompactionChange] = []
        for section in _TUNABLE_STAGE1_SECTIONS:
            if observed[section] == 0:
                continue
            usage_rate = used[section] / observed[section]
            if usage_rate <= COMPACTION_DROP_USAGE_RATE:
                candidate_changes.append(CompactionChange(
                    query_type=query_type,
                    section=section,
                    observed_count=observed[section],
                    used_count=used[section],
                    usage_rate=round(usage_rate, 4),
                    action="drop",
                ))
                continue
            proposed_sections.append(section)
            if section == "top_risk" and usage_rate >= COMPACTION_DETAIL_USAGE_RATE:
                proposed_detail_sections.append(section)
                candidate_changes.append(CompactionChange(
                    query_type=query_type,
                    section=section,
                    observed_count=observed[section],
                    used_count=used[section],
                    usage_rate=round(usage_rate, 4),
                    action="preserve_detail",
                ))

        if len(proposed_sections) == 1:
            proposed_sections.append("tldr")

        current_sections, current_detail_sections = resolve_stage1_compaction_policy(
            query_type=query_type,
            config=config,
        )
        if (
            proposed_sections != current_sections
            or proposed_detail_sections != current_detail_sections
        ):
            _set_compaction_policy(
                config,
                query_type,
                proposed_sections,
                proposed_detail_sections,
            )
            changes.extend(candidate_changes)

    return changes


def _load_session(sessions_dir: Path, session_id: str) -> dict[str, Any] | None:
    path = sessions_dir / f"{session_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _stage3_content(session: dict[str, Any]) -> str:
    stage3 = session.get("stage3")
    if isinstance(stage3, dict):
        content = stage3.get("content")
        return content if isinstance(content, str) else ""
    return ""


def _members_routed(row: dict[str, Any]) -> list[str]:
    raw = row.get("members_routed")
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if not isinstance(raw, str) or not raw.strip():
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if item]


def _member_aliases(member: BoardMember) -> list[str]:
    aliases = [member.id, member.title]
    role_head = member.role.split("/", 1)[0].strip()
    if role_head:
        aliases.append(role_head)
    return _dedupe([alias for alias in aliases if len(alias.strip()) >= 3])


def _group_observations_by_query_type(
    observations: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for observation in observations:
        by_query[observation["query_type"]].append(observation)
    return by_query


def _eligible_query_type_count(
    observations: list[dict[str, Any]],
    *,
    min_sessions: int,
) -> int:
    return sum(
        1
        for rows in _group_observations_by_query_type(observations).values()
        if len(rows) >= min_sessions
    )


def _non_chair_citations(row: dict[str, Any]) -> set[str]:
    return {mid for mid in row["cited_member_ids"] if mid != CHAIRPERSON_ID}


def _section_used_in_synthesis(section_text: str, synthesis: str) -> bool:
    section_tokens = _meaningful_tokens(section_text)
    if len(section_tokens) < 2:
        return False
    synthesis_tokens = _meaningful_tokens(synthesis)
    overlap = section_tokens & synthesis_tokens
    if len(overlap) < 2:
        return False
    return len(overlap) / len(section_tokens) >= 0.35


def _meaningful_tokens(text: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {
        token
        for token in tokens
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _current_suppressed_members(config: HarnessConfig, query_type: str) -> list[str]:
    query_config = config.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        return []
    routing = query_config.get("routing")
    if not isinstance(routing, dict):
        return []
    suppressed = routing.get("suppressed_member_ids")
    if not isinstance(suppressed, list):
        return []
    return [str(member_id) for member_id in suppressed if member_id]


def _set_suppressed_members(
    config: HarnessConfig,
    query_type: str,
    member_ids: list[str],
) -> None:
    query_config = _query_config(config, query_type)
    routing = query_config.get("routing")
    if not isinstance(routing, dict):
        routing = {}
        query_config["routing"] = routing
    routing["suppressed_member_ids"] = member_ids


def _set_compaction_policy(
    config: HarnessConfig,
    query_type: str,
    sections: list[str],
    detail_sections: list[str],
) -> None:
    query_config = _query_config(config, query_type)
    compaction = query_config.get("compaction")
    if not isinstance(compaction, dict):
        compaction = {}
        query_config["compaction"] = compaction
    compaction["stage1_sections"] = sections
    compaction["stage1_detail_sections"] = detail_sections


def _query_config(config: HarnessConfig, query_type: str) -> dict:
    if not isinstance(config.per_query_type, dict):
        config.per_query_type = {}
    query_config = config.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        query_config = {}
        config.per_query_type[query_type] = query_config
    return query_config


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
