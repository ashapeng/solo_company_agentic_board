"""Stable adapter shapes for board integration surfaces."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from server.execution import parse_delegation_plan
from server.memory.sotb import generate_sotb_update


class BoardErrorCode:
    """Stable error codes for API/tool callers."""

    DELIBERATION_FAILED = "deliberation_failed"
    VERIFICATION_FAILED = "verification_failed"
    MEMORY_PROPOSAL_PARSE_FAILED = "memory_proposal_parse_failed"
    UNAVAILABLE_CAPABILITY = "unavailable_capability"


_SECTION_ALIASES = {
    "executive_summary": "Executive Summary",
    "critical_findings": "Critical Findings",
    "strategic_direction": "Strategic Direction",
    "architecture_design": "Architecture & Design",
    "security_posture": "Security Posture",
    "implementation_plan": "Implementation Plan",
    "risk_register": "Risk Register",
    "dissenting_views": "Dissenting Views",
    "next_steps": "Next Steps",
    "delegation_plan": "Delegation Plan",
    "sotb_update": "SOTB Update",
}


@dataclass
class BoardDecisionProjection:
    prepared_by: str = ""
    decision_authority: str = ""
    participants: list[str] = field(default_factory=list)
    decision_date: str = ""
    session_id: str = ""
    status: str = ""
    assumptions: list[str] = field(default_factory=list)
    accountable_owners: list[str] = field(default_factory=list)
    executive_summary: str = ""
    critical_findings: list[str] = field(default_factory=list)
    strategic_direction: str = ""
    architecture_design: str = ""
    security_posture: str = ""
    implementation_plan: list[str] = field(default_factory=list)
    risk_register: list[str] = field(default_factory=list)
    dissenting_views: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    raw_sections: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def project_board_decision(synthesis_content: str | None) -> dict[str, Any] | None:
    """Project chairman Markdown into a small structured contract.

    This is intentionally conservative: the chairman remains the source of truth, while
    integrations get stable fields without parsing the full Markdown themselves.
    """
    if not synthesis_content:
        return None

    sections = _extract_markdown_sections(synthesis_content)
    if not sections:
        return BoardDecisionProjection(
            executive_summary=synthesis_content.strip(),
        ).to_dict()

    projected = BoardDecisionProjection(
        executive_summary=sections.get("Executive Summary", "").strip(),
        critical_findings=_extract_listish_items(sections.get("Critical Findings", "")),
        strategic_direction=sections.get("Strategic Direction", "").strip(),
        architecture_design=sections.get("Architecture & Design", "").strip(),
        security_posture=sections.get("Security Posture", "").strip(),
        implementation_plan=_extract_listish_items(sections.get("Implementation Plan", "")),
        risk_register=_extract_listish_items(sections.get("Risk Register", "")),
        dissenting_views=_extract_listish_items(sections.get("Dissenting Views", "")),
        next_steps=_extract_listish_items(sections.get("Next Steps", "")),
        raw_sections={value: sections.get(value, "") for value in _SECTION_ALIASES.values()},
    )
    return projected.to_dict()


def verification_to_dict(result: Any) -> dict[str, Any] | None:
    """Convert a verification object into a JSON-safe dict."""
    if result is None:
        return None
    if hasattr(result, "to_dict"):
        return result.to_dict()
    if hasattr(result, "__dataclass_fields__"):
        return asdict(result)
    if isinstance(result, dict):
        return result
    return {"result": str(result)}


def adapt_session_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return the stable integration contract for a saved or live board session."""
    stage3 = record.get("stage3") or {}
    synthesis = stage3.get("content") if isinstance(stage3, dict) else None
    memory = record.get("memory") or {}
    proposed_sotb_update = memory.get("proposed_sotb_update")
    if not proposed_sotb_update and synthesis:
        proposed_sotb_update = generate_sotb_update(synthesis)
    delegation_plan = record.get("delegation_plan")
    if delegation_plan is None:
        delegation_plan = parse_delegation_plan(
            synthesis,
            session_id=str(record.get("session_id") or ""),
        )

    # Extract secretary brief if available
    secretary_brief_raw = record.get("secretary_brief")
    secretary_brief_content = None
    if isinstance(secretary_brief_raw, dict):
        secretary_brief_content = secretary_brief_raw.get("content")

    return {
        "session_id": record.get("session_id"),
        "user_query": record.get("user_query"),
        "classification": record.get("classification"),
        "participation": record.get("participation", []),
        "decision": record.get("decision") or project_board_decision(synthesis),
        "secretary_brief": secretary_brief_content,
        "delegation_plan": delegation_plan,
        "verification": record.get("verification"),
        "memory": {
            "proposed_sotb_update": proposed_sotb_update,
            "requires_approval": memory.get("requires_approval", True),
            "source": memory.get("source"),
            "warnings": memory.get("warnings", []),
        },
        "metrics": record.get("metrics"),
        "artifacts": {
            "session_json_path": f"data/sessions/{record.get('session_id')}.json"
            if record.get("session_id")
            else None,
        },
    }


def _extract_markdown_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None

    for line in markdown.splitlines():
        match = re.match(r"^\s{0,3}#{2,3}\s+(.+?)\s*$", line)
        if match:
            heading = _normalize_heading(match.group(1))
            current = heading
            sections.setdefault(current, [])
            continue
        if current:
            sections[current].append(line)

    return {heading: "\n".join(lines).strip() for heading, lines in sections.items()}


def _normalize_heading(raw: str) -> str:
    heading = re.sub(r"\s+", " ", raw.strip().rstrip(":"))
    lower = heading.lower()
    for canonical in _SECTION_ALIASES.values():
        if lower == canonical.lower():
            return canonical
    return heading


def _extract_listish_items(section: str) -> list[str]:
    text = section.strip()
    if not text:
        return []

    items: list[str] = []
    current: list[str] = []
    item_re = re.compile(r"^\s*(?:[-*]\s+|\d+[.)]\s+)(.+)$")

    for line in text.splitlines():
        match = item_re.match(line)
        if match:
            if current:
                items.append(" ".join(current).strip())
            current = [match.group(1).strip()]
        elif current and line.strip():
            current.append(line.strip())
        elif current:
            items.append(" ".join(current).strip())
            current = []

    if current:
        items.append(" ".join(current).strip())

    return items or [text]
