"""Loader: reads member definitions from markdown files with YAML frontmatter."""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from .config import BoardMember

logger = logging.getLogger(__name__)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """Parse YAML frontmatter and markdown body from a file's text content.

    Expects the file to start with ``---``, followed by YAML, then another
    ``---``, and finally the markdown body.

    Returns (frontmatter_dict, markdown_body).
    """
    text = text.strip()
    if not text.startswith("---"):
        raise ValueError("File does not start with YAML frontmatter (---)")

    # Split on the second '---' delimiter
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError("Could not find closing --- for YAML frontmatter")

    frontmatter_raw = parts[1].strip()
    body = parts[2].strip()

    frontmatter = yaml.safe_load(frontmatter_raw)
    if not isinstance(frontmatter, dict):
        raise ValueError("YAML frontmatter did not parse as a dictionary")

    return frontmatter, body


def _extract_stage2_behavior(body: str) -> str:
    """Extract the '## Stage 2 Behavior' section from the markdown body.

    Returns the section content, or empty string if not found.
    """
    lines = body.split("\n")
    capture = False
    captured: list[str] = []

    for line in lines:
        if line.strip().lower().startswith("## stage 2 behavior"):
            capture = True
            continue
        if capture:
            # Stop at the next ## heading
            if line.strip().startswith("## "):
                break
            captured.append(line)

    return "\n".join(captured).strip()


def _parse_member_intake(raw):
    """Parse a member's `intake:` frontmatter block into MemberIntake or None."""
    from .config import MemberIntake

    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"member intake must be a mapping, got {type(raw).__name__}")
    required = (
        "clarifying_question",
        "immediate_concern",
        "proposed_path",
        "required_execution_unit",
    )
    missing = [k for k in required if not str(raw.get(k, "")).strip()]
    if missing:
        raise ValueError(f"intake missing fields: {missing}")
    return MemberIntake(
        clarifying_question=str(raw["clarifying_question"]).strip(),
        immediate_concern=str(raw["immediate_concern"]).strip(),
        proposed_path=str(raw["proposed_path"]).strip(),
        required_execution_unit=str(raw["required_execution_unit"]).strip(),
    )


_DEFAULT_MEMBERS_DIR = Path(__file__).resolve().parent.parent / "members"


def load_members(
    directory: str | Path | None = None,
    *,
    include_shelved_ids: set[str] | None = None,
) -> list[BoardMember]:
    """Load board members from markdown files in the given directory.

    Skips files starting with ``_`` (templates, test files).
    Validates that each file has required fields: id, title, role.
    Returns members sorted by priority (descending).
    """
    members_dir = Path(directory) if directory else _DEFAULT_MEMBERS_DIR
    if not members_dir.is_dir():
        logger.warning("Members directory '%s' does not exist; returning empty list", directory)
        return []

    members: list[BoardMember] = []

    include_shelved_ids = include_shelved_ids or set()

    for filepath in sorted(members_dir.glob("*.md")):
        # Skip templates/private files. Shelved members can be included explicitly
        # by stage profile using their file stem without the leading underscore.
        is_shelved = filepath.name.startswith("_")
        is_activated_shelved = False
        if is_shelved:
            shelved_id = filepath.stem.lstrip("_")
            if shelved_id not in include_shelved_ids:
                logger.debug("Skipping template/private file: %s", filepath.name)
                continue
            is_activated_shelved = True

        logger.debug("Loading member from: %s", filepath.name)
        text = filepath.read_text(encoding="utf-8")

        try:
            frontmatter, body = _parse_frontmatter(text)
        except ValueError as e:
            raise ValueError(f"Error parsing {filepath.name}: {e}") from e

        # Validate required fields
        for required in ("id", "title", "role"):
            if required not in frontmatter or not frontmatter[required]:
                raise ValueError(
                    f"Member file {filepath.name} is missing required field: '{required}'"
                )

        # Extract stage2 behavior from body
        stage2_behavior = _extract_stage2_behavior(body)

        # Build expertise list
        expertise_raw = frontmatter.get("expertise", [])
        if isinstance(expertise_raw, str):
            expertise = [e.strip() for e in expertise_raw.split(",") if e.strip()]
        elif isinstance(expertise_raw, list):
            expertise = [str(e) for e in expertise_raw]
        else:
            expertise = []

        # Build tags list
        tags_raw = frontmatter.get("tags", [])
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        else:
            tags = []

        # Handle model_override (YAML null -> None)
        model_override = frontmatter.get("model_override")
        if model_override is None or model_override == "null":
            model_override = None

        member = BoardMember(
            id=frontmatter["id"],
            title=frontmatter["title"],
            role=frontmatter["role"],
            expertise=expertise,
            system_prompt=body,
            stage2_behavior=stage2_behavior,
            model_override=model_override,
            priority=int(frontmatter.get("priority", 0)),
            tags=tags,
            intake=_parse_member_intake(frontmatter.get("intake")),
            evidence_required=bool(frontmatter.get("evidence_required", False)),
        )
        # Intake frontmatter is required for active council members (not shelved, not chairperson).
        # Shelved members that are explicitly activated also must satisfy the intake requirement.
        is_active_council = (not is_shelved) or is_activated_shelved
        if is_active_council and member.id != "chairperson" and member.intake is None:
            raise ValueError(
                f"Council member '{member.id}' is missing required 'intake:' frontmatter block."
            )
        members.append(member)
        logger.info("Loaded member: %s (%s)", member.id, member.title)

    # Sort by priority descending
    members.sort(key=lambda m: m.priority, reverse=True)
    return members
