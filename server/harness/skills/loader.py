"""Loader for member-declared skill bundles.

Each skill lives at ``server/harness/skills/_library/<name>/SKILL.md``
with YAML frontmatter (``name``, ``description``) plus a markdown body.

Public API:

- :func:`load_skills` — load a list of skills by name, in request order.
- :func:`list_skills` — enumerate every skill in the library.
- :data:`MAX_SKILL_BODY_CHARS` — body-length cap; overflow is truncated
  with the ``[…truncated…]`` marker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MAX_SKILL_BODY_CHARS: int = 8000
TRUNCATION_MARKER: str = "[…truncated…]"

_DEFAULT_LIBRARY_DIR = Path(__file__).resolve().parent / "_library"


@dataclass(frozen=True)
class Skill:
    """A single member-declared skill bundle."""

    name: str
    description: str
    body: str
    path: Path


def _parse_skill_file(path: Path) -> Skill | None:
    """Parse one SKILL.md file. Returns None on any failure (warn + skip)."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Skill file unreadable at %s: %s", path, exc)
        return None

    if not text.startswith("---"):
        logger.warning("Skill file %s missing YAML frontmatter; skipping", path)
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.warning("Skill file %s missing closing ---; skipping", path)
        return None

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.warning("Skill file %s has malformed YAML: %s; skipping", path, exc)
        return None

    if not isinstance(frontmatter, dict):
        logger.warning("Skill file %s frontmatter is not a mapping; skipping", path)
        return None

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        logger.warning("Skill file %s missing 'name'; skipping", path)
        return None
    if description is None:
        description = ""
    description = str(description).strip()

    body = parts[2].strip()
    if len(body) > MAX_SKILL_BODY_CHARS:
        logger.warning(
            "Skill %s body length %d exceeds MAX_SKILL_BODY_CHARS=%d; truncating",
            name,
            len(body),
            MAX_SKILL_BODY_CHARS,
        )
        body = body[:MAX_SKILL_BODY_CHARS] + TRUNCATION_MARKER

    return Skill(name=name.strip(), description=description, body=body, path=path)


def load_skills(
    names: list[str],
    *,
    library_dir: Path | None = None,
) -> list[Skill]:
    """Load skills by name in request order.

    Unknown names emit a ``logging.warning`` and are dropped from the
    returned list. Callers may also inspect the warning records via
    ``caplog`` or compute the diff between ``names`` and
    ``[s.name for s in returned]`` to detect misses.
    """
    base = library_dir if library_dir is not None else _DEFAULT_LIBRARY_DIR
    loaded: list[Skill] = []
    for name in names:
        skill_path = base / name / "SKILL.md"
        if not skill_path.is_file():
            logger.warning("Skill %r not found at %s; skipping", name, skill_path)
            continue
        parsed = _parse_skill_file(skill_path)
        if parsed is None:
            continue
        loaded.append(parsed)
    return loaded


def list_skills(*, library_dir: Path | None = None) -> list[Skill]:
    """Enumerate every well-formed SKILL.md in the library, alphabetically."""
    base = library_dir if library_dir is not None else _DEFAULT_LIBRARY_DIR
    if not base.is_dir():
        return []
    out: list[Skill] = []
    for skill_dir in sorted(base.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        parsed = _parse_skill_file(skill_path)
        if parsed is not None:
            out.append(parsed)
    return out
