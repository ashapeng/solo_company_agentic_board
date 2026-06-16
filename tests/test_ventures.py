import unittest
from typing import get_args

from server.ventures import (
    DEFAULT_VENTURE_ID,
    DEFAULT_VENTURE_SLUG,
    VentureError,
    VentureStatus,
    create_venture,
    ensure_default_venture,
    get_venture,
    get_venture_by_slug,
    list_ventures,
    update_venture,
    venture_slug,
)


class VentureStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        from pathlib import Path

        self.db_path = Path(self._tmp.name) / "harness_ledger.db"

    def test_status_type_is_literal_alias(self):
        self.assertEqual(("active", "archived"), get_args(VentureStatus))

    def test_create_get_roundtrip(self):
        created = create_venture("Acme Labs", db_path=self.db_path)
        self.assertTrue(created["id"])
        self.assertEqual("Acme Labs", created["name"])
        self.assertEqual("acme-labs", created["slug"])
        self.assertEqual("active", created["status"])
        self.assertTrue(created["created_at"])
        self.assertTrue(created["updated_at"])

        reloaded = get_venture(created["id"], db_path=self.db_path)
        self.assertEqual(created["id"], reloaded["id"])
        self.assertEqual("acme-labs", reloaded["slug"])

        by_slug = get_venture_by_slug("acme-labs", db_path=self.db_path)
        self.assertEqual(created["id"], by_slug["id"])

    def test_get_missing_returns_none(self):
        self.assertIsNone(get_venture("nope", db_path=self.db_path))
        self.assertIsNone(get_venture_by_slug("nope", db_path=self.db_path))

    def test_slug_derivation_and_safety(self):
        self.assertEqual("my-co-v2", venture_slug("My Co / v2!"))
        # No path separators or traversal sequences leak into the slug.
        for raw in ("My Co / v2!", "../etc/passwd", "a/b\\c", "..", "  ", "***"):
            slug = venture_slug(raw)
            self.assertNotIn("/", slug)
            self.assertNotIn("\\", slug)
            self.assertNotIn("..", slug)
            self.assertTrue(slug)
            self.assertTrue(all(c.isalnum() or c == "-" for c in slug))
        # Empty/symbol-only input falls back to a stable hash slug.
        self.assertTrue(venture_slug("***").startswith("v-"))
        self.assertEqual(venture_slug(""), venture_slug(""))
        # Long names are capped.
        self.assertLessEqual(len(venture_slug("x" * 200)), 40)

    def test_create_with_explicit_slug_is_sanitized(self):
        created = create_venture(
            "Sketchy", slug="../../escape", db_path=self.db_path
        )
        self.assertNotIn("/", created["slug"])
        self.assertNotIn("..", created["slug"])

    def test_duplicate_slug_rejected(self):
        create_venture("Acme Labs", db_path=self.db_path)
        with self.assertRaises(VentureError):
            create_venture("Acme  Labs", db_path=self.db_path)

    def test_ensure_default_venture_idempotent(self):
        first = ensure_default_venture(db_path=self.db_path)
        self.assertEqual(DEFAULT_VENTURE_ID, first["id"])
        self.assertEqual(DEFAULT_VENTURE_SLUG, first["slug"])
        self.assertEqual("Default", first["name"])

        second = ensure_default_venture(db_path=self.db_path)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["created_at"], second["created_at"])

        defaults = [v for v in list_ventures(db_path=self.db_path) if v["id"] == DEFAULT_VENTURE_ID]
        self.assertEqual(1, len(defaults))

    def test_list_filtering_by_status(self):
        active = create_venture("Active Co", db_path=self.db_path)
        archived = create_venture("Archived Co", db_path=self.db_path)
        update_venture(archived["id"], status="archived", db_path=self.db_path)

        all_ventures = list_ventures(db_path=self.db_path)
        self.assertEqual(2, len(all_ventures))

        only_active = list_ventures(status="active", db_path=self.db_path)
        self.assertEqual([active["id"]], [v["id"] for v in only_active])

        only_archived = list_ventures(status="archived", db_path=self.db_path)
        self.assertEqual([archived["id"]], [v["id"] for v in only_archived])

    def test_update_venture_name_and_status(self):
        created = create_venture("Old Name", db_path=self.db_path)
        updated = update_venture(
            created["id"], name="New Name", status="archived", db_path=self.db_path
        )
        self.assertEqual("New Name", updated["name"])
        self.assertEqual("archived", updated["status"])
        # Slug is stable across renames.
        self.assertEqual(created["slug"], updated["slug"])

    def test_update_missing_raises(self):
        with self.assertRaises(VentureError):
            update_venture("ghost", name="x", db_path=self.db_path)

    def test_invalid_status_rejected(self):
        with self.assertRaises(VentureError):
            create_venture("Bad", status="weird", db_path=self.db_path)


if __name__ == "__main__":
    unittest.main()
