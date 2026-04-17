"""Memory proposal helpers for human-approved SOTB updates."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import unified_diff
from typing import Any

from .sotb import generate_sotb_update, read_sotb


SOTB_SECTIONS = (
    "Active Decisions",
    "Risk Register",
    "Established Positions",
    "Open Questions",
    "Last Session",
)


@dataclass
class MemoryProposal:
    proposed_sotb_update: str | None
    requires_approval: bool = True
    source: str = "chairperson_synthesis"
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def propose_memory_update(
    synthesis_content: str | None,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Create a reviewable memory proposal without mutating durable memory."""
    if not synthesis_content:
        return MemoryProposal(
            proposed_sotb_update=None,
            warnings=["No chairman synthesis was available to review."],
        ).to_dict()

    update = generate_sotb_update(synthesis_content)
    warnings: list[str] = []
    if not update:
        warnings.append("No SOTB Update section found in chairman synthesis.")

    proposal = MemoryProposal(
        proposed_sotb_update=update,
        source=f"session:{session_id}" if session_id else "chairperson_synthesis",
        warnings=warnings,
    )
    return proposal.to_dict()


def review_sotb_update(
    proposed_update: str | None,
    *,
    session_id: str = "",
    current_sotb: str | None = None,
) -> dict[str, Any]:
    """Return a reviewable SOTB candidate and diff without writing durable memory."""
    current = read_sotb() if current_sotb is None else current_sotb
    update = (proposed_update or "").strip()
    warnings: list[str] = []

    if not update:
        warnings.append("No proposed SOTB update was provided.")
        candidate = current
    else:
        candidate = _candidate_sotb(current, update, session_id=session_id)

    diff = "\n".join(unified_diff(
        current.splitlines(),
        candidate.splitlines(),
        fromfile="current_sotb.md",
        tofile="candidate_sotb.md",
        lineterm="",
    ))

    return {
        "requires_approval": True,
        "session_id": session_id,
        "proposed_sotb_update": update or None,
        "candidate_sotb": candidate,
        "diff": diff,
        "current_word_count": len(current.split()),
        "candidate_word_count": len(candidate.split()),
        "warnings": warnings,
    }


def _candidate_sotb(current: str, update: str, *, session_id: str = "") -> str:
    section_updates = _extract_section_updates(update)
    if section_updates:
        candidate = current
        for section, section_update in section_updates.items():
            if section == "Last Session":
                candidate = _replace_last_session(candidate, section_update, session_id=session_id)
            else:
                candidate = _append_to_section(candidate, section, section_update, session_id=session_id)
        return candidate

    return _replace_last_session(current, update, session_id=session_id)


def _replace_last_session(current: str, update: str, *, session_id: str = "") -> str:
    marker = "## Last Session"
    replacement = f"{marker}\nSession: {session_id or '[pending]'}\n\n{update}".rstrip()

    if marker not in current:
        return (current.rstrip() + "\n\n" + replacement + "\n").lstrip()

    before, _sep, after = current.partition(marker)
    following_section = after.find("\n## ")
    if following_section == -1:
        return before.rstrip() + "\n\n" + replacement + "\n"

    rest = after[following_section + 1:]
    return before.rstrip() + "\n\n" + replacement + "\n\n" + rest.lstrip()


def _extract_section_updates(update: str) -> dict[str, str]:
    sections_by_lower = {section.lower(): section for section in SOTB_SECTIONS}
    section_updates: dict[str, list[str]] = {}
    current_section: str | None = None

    for line in update.splitlines():
        heading = _section_heading(line)
        if heading:
            canonical = sections_by_lower.get(heading.lower())
            if canonical:
                current_section = canonical
                section_updates.setdefault(canonical, [])
                continue

        if current_section:
            section_updates[current_section].append(line)

    return {
        section: "\n".join(lines).strip()
        for section, lines in section_updates.items()
        if "\n".join(lines).strip()
    }


def _append_to_section(current: str, section: str, update: str, *, session_id: str = "") -> str:
    marker = f"## {section}"
    source = f"_Source: session:{session_id or '[pending]'}_"
    addition = f"{source}\n{update}".strip()

    if marker not in current:
        return (current.rstrip() + f"\n\n{marker}\n{addition}\n").lstrip()

    before, _sep, after = current.partition(marker)
    following_section = after.find("\n## ")

    if following_section == -1:
        existing = after.strip()
        return before.rstrip() + f"\n\n{marker}\n{existing}\n\n{addition}\n"

    existing = after[:following_section].strip()
    rest = after[following_section + 1:]
    return before.rstrip() + f"\n\n{marker}\n{existing}\n\n{addition}\n\n" + rest.lstrip()


def _section_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith(("## ", "### ")):
        return None
    heading = stripped.lstrip("#").strip().rstrip(":")
    return " ".join(heading.split())
