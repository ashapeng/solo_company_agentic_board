import unittest
from typing import get_args

from server.initiatives import (
    ApprovalState,
    CarryoverDecisionValue,
    CreatedFrom,
    FounderOutcome,
    InitiativeError,
    InitiativeStatus,
    LinkRelationship,
    LinkTargetType,
    activate_initiative,
    close_initiative,
    create_initiative,
    create_link,
    delete_link,
    get_initiative,
    list_initiatives,
    list_links,
    update_initiative,
)


class InitiativeStoreContractTest(unittest.TestCase):
    def test_public_state_types_are_literal_aliases(self):
        self.assertEqual(("draft", "active", "closed"), get_args(InitiativeStatus))
        self.assertEqual(("draft", "approved"), get_args(ApprovalState))
        self.assertEqual(("manual", "founder_command", "board_suggestion"), get_args(CreatedFrom))
        self.assertEqual(("success", "failure", "mixed"), get_args(FounderOutcome))
        self.assertEqual(
            ("sotb_entry", "initiative", "board_session", "delegated_task", "artifact"),
            get_args(LinkTargetType),
        )
        self.assertEqual(("context", "output", "carryover", "evidence", "artifact"), get_args(LinkRelationship))
        self.assertEqual(("carry_over", "abandon", "backlog"), get_args(CarryoverDecisionValue))

    def test_create_get_list_activate_initiative(self):
        db_path = self._db_path()

        created = create_initiative(
            title="Ship onboarding slice",
            objective="Validate the first onboarding workflow.",
            success_criteria=["Founder can complete setup"],
            departments=["product", "engineering"],
            db_path=db_path,
        )

        self.assertTrue(created["id"].startswith("init_"))
        self.assertEqual("draft", created["status"])
        self.assertEqual("draft", created["approval_state"])
        self.assertTrue(created["timebox_start"])
        self.assertTrue(created["timebox_end"])

        reloaded = get_initiative(created["id"], db_path=db_path)
        self.assertEqual(created["id"], reloaded["id"])

        listed = list_initiatives(db_path=db_path)
        self.assertEqual([created["id"]], [initiative["id"] for initiative in listed])

        activated = activate_initiative(created["id"], db_path=db_path)
        self.assertEqual("active", activated["status"])
        self.assertEqual("approved", activated["approval_state"])

    def test_initiative_links_and_closeout(self):
        db_path = self._db_path()
        initiative = create_initiative(
            title="Instrument activation",
            objective="Capture evidence for activation decisions.",
            db_path=db_path,
        )

        link = create_link(
            initiative["id"],
            target_type="artifact",
            target_id="data/artifacts/activation.md",
            relationship="evidence",
            db_path=db_path,
        )
        self.assertTrue(link["id"].startswith("link_"))
        self.assertEqual([link["id"]], [item["id"] for item in list_links(initiative["id"], db_path=db_path)])

        closed = close_initiative(
            initiative["id"],
            founder_outcome="mixed",
            founder_notes="Activation improved, retention remains unclear.",
            retrospective_session_id="board_retrospective_1",
            memory_proposals=["Record onboarding friction as active risk."],
            carryover_decisions=[
                {"task_id": "task_followup", "decision": "carry_over"},
                {"task_id": "task_archive", "decision": "backlog"},
            ],
            db_path=db_path,
        )

        self.assertEqual("closed", closed["status"])
        self.assertEqual("mixed", closed["closeout"]["founder_outcome"])
        self.assertEqual("carry_over", closed["closeout"]["carryover_decisions"][0]["decision"])

        reloaded = get_initiative(initiative["id"], db_path=db_path)
        self.assertEqual("board_retrospective_1", reloaded["closeout"]["retrospective_session_id"])

    def test_invalid_status_transition_rejected(self):
        db_path = self._db_path()
        initiative = create_initiative(
            title="Retire stale experiment",
            objective="Close the initiative after review.",
            db_path=db_path,
        )
        close_initiative(
            initiative["id"],
            founder_outcome="failure",
            founder_notes="No customer pull.",
            retrospective_session_id="board_retrospective_2",
            memory_proposals=[],
            carryover_decisions=[],
            db_path=db_path,
        )

        with self.assertRaises(InitiativeError):
            activate_initiative(initiative["id"], db_path=db_path)

    def test_update_initiative_rejects_closed_edits(self):
        db_path = self._db_path()
        initiative = create_initiative(
            title="Draft market test",
            objective="Probe pricing interest.",
            db_path=db_path,
        )

        updated = update_initiative(
            initiative["id"],
            title="Updated market test",
            objective="Probe pricing and packaging interest.",
            success_criteria=["Three qualified calls"],
            departments=["strategy"],
            db_path=db_path,
        )
        self.assertEqual("Updated market test", updated["title"])
        self.assertEqual("Probe pricing and packaging interest.", updated["objective"])
        self.assertEqual(["strategy"], updated["departments"])

        close_initiative(
            initiative["id"],
            founder_outcome="success",
            founder_notes="Strong signal.",
            retrospective_session_id="board_retrospective_3",
            memory_proposals=[],
            carryover_decisions=[],
            db_path=db_path,
        )

        with self.assertRaises(InitiativeError):
            update_initiative(initiative["id"], title="Too late", db_path=db_path)

    def test_delete_link_removes_link_and_rejects_missing_link(self):
        db_path = self._db_path()
        initiative = create_initiative(
            title="Connect evidence",
            objective="Keep linked evidence tidy.",
            db_path=db_path,
        )
        link = create_link(
            initiative["id"],
            target_type="delegated_task",
            target_id="task_123",
            relationship="carryover",
            db_path=db_path,
        )

        deleted = delete_link(initiative["id"], link["id"], db_path=db_path)

        self.assertEqual(link["id"], deleted["id"])
        self.assertEqual([], list_links(initiative["id"], db_path=db_path))
        with self.assertRaises(InitiativeError):
            delete_link(initiative["id"], link["id"], db_path=db_path)

    def _db_path(self):
        return self.tmp_path / "ledger.db"

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
