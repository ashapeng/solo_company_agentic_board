"""State of the Board (SOTB) — persistent institutional memory."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SOTB_PATH = Path(__file__).resolve().parent.parent / "memory" / "sotb.md"
MAX_SOTB_WORDS = 1000


def read_sotb() -> str:
    """Read the current State of the Board. Returns empty string if not found."""
    if not SOTB_PATH.exists():
        return ""
    return SOTB_PATH.read_text(encoding="utf-8")


def generate_sotb_update(synthesis_content: str) -> str | None:
    """Extract the ## SOTB Update section from chairman's synthesis.

    Returns the update text, or None if no update section found.
    """
    # Look for a ## SOTB Update section in the synthesis
    # Parse it out between ## SOTB Update and the next ## heading (or end)
    lines = synthesis_content.split("\n")
    capture = False
    captured = []

    for line in lines:
        stripped = line.strip().lower()
        if stripped.startswith("## sotb update") or stripped.startswith("### sotb update"):
            capture = True
            continue
        if capture:
            if line.strip().startswith("## ") or line.strip().startswith("### "):
                break
            captured.append(line)

    if not captured:
        return None

    return "\n".join(captured).strip()


def apply_sotb_update(update_text: str, session_id: str = "") -> None:
    """Apply an update to the SOTB file.

    Reads current SOTB, appends the update to the relevant sections,
    and writes back. Keeps the file under MAX_SOTB_WORDS.
    """
    current = read_sotb()

    # Build new SOTB
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Parse the update to find what sections it updates
    # Simple approach: replace the "Last Session" section and append decisions
    new_sotb = current

    # Update "Last Session" section
    last_session_pattern = r"## Last Session\n.*?(?=\n## |\Z)"
    new_last = f"## Last Session\nSession: {session_id} | Updated: {now}\n\n{update_text}"

    if re.search(last_session_pattern, new_sotb, re.DOTALL):
        new_sotb = re.sub(last_session_pattern, new_last, new_sotb, flags=re.DOTALL)
    else:
        new_sotb += f"\n\n{new_last}"

    # Update the header timestamp
    new_sotb = re.sub(
        r"> Last updated:.*?\|",
        f"> Last updated: {now} |",
        new_sotb,
    )

    # Trim if over word limit
    words = new_sotb.split()
    if len(words) > MAX_SOTB_WORDS:
        # Keep the first MAX_SOTB_WORDS words
        new_sotb = " ".join(words[:MAX_SOTB_WORDS]) + "\n\n[...truncated to stay under word limit]"

    SOTB_PATH.write_text(new_sotb, encoding="utf-8")
    logger.info("SOTB updated: %s (%d words)", SOTB_PATH, len(new_sotb.split()))
