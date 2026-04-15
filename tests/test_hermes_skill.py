from pathlib import Path
import unittest

import yaml


SKILL_PATHS = [
    Path("hermes/skills/agentic-board/SKILL.md"),
    Path("hermes/skills/board-memory-update/SKILL.md"),
    Path("hermes/skills/role-gap-review/SKILL.md"),
]


class HermesSkillTest(unittest.TestCase):
    def test_agentic_board_skill_frontmatter(self):
        text = SKILL_PATHS[0].read_text(encoding="utf-8")
        _, raw_frontmatter, _ = text.split("---", 2)
        frontmatter = yaml.safe_load(raw_frontmatter)

        self.assertEqual("agentic-board", frontmatter["name"])
        self.assertIn("terminal", frontmatter["metadata"]["hermes"]["requires_toolsets"])
        self.assertIn("files", frontmatter["metadata"]["hermes"]["requires_toolsets"])

    def test_agentic_board_skill_preserves_memory_gate(self):
        text = SKILL_PATHS[0].read_text(encoding="utf-8")

        self.assertIn("data/sessions/<session_id>.json", text)
        self.assertIn("memory.proposed_sotb_update", text)
        self.assertIn("Do not call `PUT /sotb`", text)
        self.assertIn("requires_approval", text)

    def test_all_hermes_skills_have_frontmatter(self):
        for path in SKILL_PATHS:
            text = path.read_text(encoding="utf-8")
            _, raw_frontmatter, _ = text.split("---", 2)
            frontmatter = yaml.safe_load(raw_frontmatter)

            self.assertIn("name", frontmatter)
            self.assertIn("description", frontmatter)
            self.assertIn("metadata", frontmatter)


if __name__ == "__main__":
    unittest.main()
