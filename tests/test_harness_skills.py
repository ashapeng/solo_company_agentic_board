"""Tests for `server.harness.skills` — loader + dataclass + library."""

from __future__ import annotations

import logging
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _make_skill(library_dir: Path, name: str, description: str, body: str) -> Path:
    skill_dir = library_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        textwrap.dedent(f"""\
            ---
            name: {name}
            description: |
              {description}
            ---
            {body}
        """),
        encoding="utf-8",
    )
    return skill_path


class SkillLoaderWellFormedTest(unittest.TestCase):
    def test_parse_well_formed_skill_file(self):
        from server.harness.skills.loader import Skill, load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            path = _make_skill(
                library,
                "pricing_research",
                "Methods for SaaS pricing research.",
                "When asked about pricing, prefer van Westendorp.",
            )

            skills = load_skills(["pricing_research"], library_dir=library)

            self.assertEqual(len(skills), 1)
            skill = skills[0]
            self.assertIsInstance(skill, Skill)
            self.assertEqual(skill.name, "pricing_research")
            self.assertIn("Methods for SaaS pricing research.", skill.description)
            self.assertIn("van Westendorp", skill.body)
            self.assertEqual(skill.path, path)


class SkillLoaderMissingTest(unittest.TestCase):
    def test_missing_skill_warns_and_is_skipped(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            library.mkdir(parents=True, exist_ok=True)

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["does_not_exist"], library_dir=library)

            self.assertEqual(skills, [])
            joined = " ".join(cm.output)
            self.assertIn("does_not_exist", joined)
            self.assertIn("not found", joined.lower())

    def test_partial_load_keeps_known_skips_unknown(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "alpha", "alpha desc", "alpha body")

            with self.assertLogs("server.harness.skills.loader", level="WARNING"):
                skills = load_skills(["alpha", "ghost"], library_dir=library)

            self.assertEqual([s.name for s in skills], ["alpha"])


class SkillLoaderMalformedTest(unittest.TestCase):
    def test_missing_frontmatter_delim_warns_and_skips(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            skill_dir = library / "broken"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "no frontmatter here, just body text",
                encoding="utf-8",
            )

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["broken"], library_dir=library)

            self.assertEqual(skills, [])
            self.assertTrue(any("frontmatter" in line.lower() for line in cm.output))

    def test_malformed_yaml_warns_and_skips(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            skill_dir = library / "bad_yaml"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: bad_yaml\ndescription: : :\n---\nbody\n",
                encoding="utf-8",
            )

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["bad_yaml"], library_dir=library)

            self.assertEqual(skills, [])
            self.assertTrue(any("malformed" in line.lower() or "yaml" in line.lower() for line in cm.output))

    def test_missing_name_field_warns_and_skips(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            skill_dir = library / "noname"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\ndescription: no name field\n---\nbody\n",
                encoding="utf-8",
            )

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["noname"], library_dir=library)

            self.assertEqual(skills, [])
            self.assertTrue(any("name" in line.lower() for line in cm.output))


class SkillBodyCapTest(unittest.TestCase):
    def test_body_within_cap_is_unchanged(self):
        from server.harness.skills.loader import MAX_SKILL_BODY_CHARS, load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            short_body = "a" * (MAX_SKILL_BODY_CHARS - 10)
            _make_skill(library, "small", "small skill", short_body)

            skills = load_skills(["small"], library_dir=library)

            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].body, short_body)
            self.assertNotIn("truncated", skills[0].body.lower())

    def test_body_over_cap_is_truncated_with_marker(self):
        from server.harness.skills.loader import (
            MAX_SKILL_BODY_CHARS,
            TRUNCATION_MARKER,
            load_skills,
        )

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            oversize_body = "b" * (MAX_SKILL_BODY_CHARS + 500)
            _make_skill(library, "big", "big skill", oversize_body)

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["big"], library_dir=library)

            self.assertEqual(len(skills), 1)
            body = skills[0].body
            self.assertTrue(body.endswith(TRUNCATION_MARKER))
            self.assertEqual(len(body), MAX_SKILL_BODY_CHARS + len(TRUNCATION_MARKER))
            self.assertTrue(any("truncating" in line.lower() for line in cm.output))

    def test_truncation_marker_uses_unicode_ellipsis(self):
        from server.harness.skills.loader import TRUNCATION_MARKER

        self.assertEqual(TRUNCATION_MARKER, "[…truncated…]")


class SkillLoaderOrderTest(unittest.TestCase):
    def test_load_skills_returns_request_order(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "first", "1st", "first body")
            _make_skill(library, "second", "2nd", "second body")
            _make_skill(library, "third", "3rd", "third body")

            skills = load_skills(
                ["third", "first", "second"],
                library_dir=library,
            )

            self.assertEqual([s.name for s in skills], ["third", "first", "second"])

    def test_unknown_interleaved_skips_only_unknown(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "alpha", "a", "abody")
            _make_skill(library, "gamma", "g", "gbody")

            with self.assertLogs("server.harness.skills.loader", level="WARNING"):
                skills = load_skills(
                    ["alpha", "beta", "gamma", "delta"],
                    library_dir=library,
                )

            self.assertEqual([s.name for s in skills], ["alpha", "gamma"])

    def test_empty_names_returns_empty_list_no_warnings(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            library.mkdir(parents=True, exist_ok=True)

            skills = load_skills([], library_dir=library)

            self.assertEqual(skills, [])


class SkillListTest(unittest.TestCase):
    def test_list_skills_returns_sorted_well_formed_only(self):
        from server.harness.skills.loader import list_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "zebra", "z", "zbody")
            _make_skill(library, "apple", "a", "abody")
            broken_dir = library / "broken"
            broken_dir.mkdir(parents=True, exist_ok=True)
            (broken_dir / "SKILL.md").write_text("no frontmatter", encoding="utf-8")

            with self.assertLogs("server.harness.skills.loader", level="WARNING"):
                listed = list_skills(library_dir=library)

            names = [s.name for s in listed]
            self.assertEqual(names, ["apple", "zebra"])

    def test_list_skills_empty_library_returns_empty(self):
        from server.harness.skills.loader import list_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            library.mkdir(parents=True, exist_ok=True)

            self.assertEqual(list_skills(library_dir=library), [])

    def test_list_skills_missing_library_returns_empty(self):
        from server.harness.skills.loader import list_skills

        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_dir"

            self.assertEqual(list_skills(library_dir=missing), [])


if __name__ == "__main__":
    unittest.main()
