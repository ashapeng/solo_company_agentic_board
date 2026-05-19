import unittest
from fastapi import HTTPException
from typing import get_args

import server.initiatives as initiative_store
import server.execution as execution_store
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

    def test_legacy_closeout_schema_accepts_nullable_retrospective_session(self):
        import sqlite3

        db_path = self._db_path()
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(
                """
                CREATE TABLE initiatives (
                    initiative_id    TEXT PRIMARY KEY,
                    title            TEXT NOT NULL,
                    objective        TEXT NOT NULL,
                    status           TEXT NOT NULL,
                    approval_state   TEXT NOT NULL,
                    created_from     TEXT NOT NULL,
                    success_criteria TEXT NOT NULL,
                    departments      TEXT NOT NULL,
                    timebox_start    TEXT NOT NULL,
                    timebox_end      TEXT NOT NULL,
                    source_session_id TEXT,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                );
                CREATE TABLE initiative_closeouts (
                    initiative_id             TEXT PRIMARY KEY,
                    founder_outcome           TEXT NOT NULL,
                    founder_notes             TEXT NOT NULL,
                    retrospective_session_id  TEXT NOT NULL,
                    memory_proposals          TEXT NOT NULL,
                    carryover_decisions       TEXT NOT NULL,
                    created_at                TEXT NOT NULL
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        initiative = create_initiative(
            title="Close legacy initiative",
            objective="Verify nullable closeout migration.",
            db_path=db_path,
        )

        closed = close_initiative(
            initiative["id"],
            founder_outcome="mixed",
            founder_notes="No retrospective session was created.",
            retrospective_session_id=None,
            memory_proposals=[],
            carryover_decisions=[],
            db_path=db_path,
        )

        self.assertIsNone(closed["closeout"]["retrospective_session_id"])

    def test_interrupted_closeout_migration_recovers_legacy_rows(self):
        import sqlite3

        db_path = self._db_path()
        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(
                """
                CREATE TABLE initiatives (
                    initiative_id    TEXT PRIMARY KEY,
                    title            TEXT NOT NULL,
                    objective        TEXT NOT NULL,
                    status           TEXT NOT NULL,
                    approval_state   TEXT NOT NULL,
                    created_from     TEXT NOT NULL,
                    success_criteria TEXT NOT NULL,
                    departments      TEXT NOT NULL,
                    timebox_start    TEXT NOT NULL,
                    timebox_end      TEXT NOT NULL,
                    source_session_id TEXT,
                    created_at       TEXT NOT NULL,
                    updated_at       TEXT NOT NULL
                );
                CREATE TABLE initiative_closeouts (
                    initiative_id             TEXT PRIMARY KEY,
                    founder_outcome           TEXT NOT NULL,
                    founder_notes             TEXT NOT NULL,
                    retrospective_session_id  TEXT,
                    memory_proposals          TEXT NOT NULL,
                    carryover_decisions       TEXT NOT NULL,
                    created_at                TEXT NOT NULL
                );
                CREATE TABLE initiative_closeouts_legacy (
                    initiative_id             TEXT PRIMARY KEY,
                    founder_outcome           TEXT NOT NULL,
                    founder_notes             TEXT NOT NULL,
                    retrospective_session_id  TEXT NOT NULL,
                    memory_proposals          TEXT NOT NULL,
                    carryover_decisions       TEXT NOT NULL,
                    created_at                TEXT NOT NULL
                );
                INSERT INTO initiatives (
                    initiative_id, title, objective, status, approval_state,
                    created_from, success_criteria, departments, timebox_start,
                    timebox_end, source_session_id, created_at, updated_at
                ) VALUES (
                    'init_legacy', 'Recovered initiative', 'Recover closeout rows.',
                    'closed', 'draft', 'manual', '[]', '[]', '2026-05-19',
                    '2026-05-26', NULL, '2026-05-19T00:00:00+00:00',
                    '2026-05-19T00:00:00+00:00'
                );
                INSERT INTO initiative_closeouts_legacy (
                    initiative_id, founder_outcome, founder_notes,
                    retrospective_session_id, memory_proposals,
                    carryover_decisions, created_at
                ) VALUES (
                    'init_legacy', 'success', 'Recovered from legacy table.',
                    'board_legacy', '[]', '[]', '2026-05-19T00:00:00+00:00'
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

        recovered = get_initiative("init_legacy", db_path=db_path)

        self.assertEqual("board_legacy", recovered["closeout"]["retrospective_session_id"])

    def _db_path(self):
        return self.tmp_path / "ledger.db"

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()


class InitiativeApiContractTest(unittest.TestCase):
    def test_create_activate_link_closeout_and_missing_get_routes(self):
        from server.api.routes import initiatives
        from server.api.schemas import (
            InitiativeActivateRequest,
            InitiativeCloseoutRequest,
            InitiativeCreateRequest,
            InitiativeLinkRequest,
        )

        created = initiatives.create_initiative(
            InitiativeCreateRequest(
                title="Launch customer onboarding",
                objective="Validate the founder-led onboarding loop.",
                success_criteria=["First customer completes setup"],
                departments=["product", "engineering"],
                source_session_id="board_source_1",
            )
        )

        self.assertEqual("draft", created["status"])
        self.assertEqual("board_source_1", created["source_session_id"])

        activated = initiatives.activate_initiative(
            created["id"],
            InitiativeActivateRequest(),
        )
        self.assertEqual("active", activated["status"])

        link = initiatives.create_link(
            created["id"],
            InitiativeLinkRequest(
                target_type="board_session",
                target_id="session_123",
                relationship="context",
            ),
        )
        self.assertEqual("board_session", link["target_type"])

        closed = initiatives.close_initiative(
            created["id"],
            InitiativeCloseoutRequest(
                founder_outcome="success",
                retrospective_session_id="session_retrospective",
                memory_proposals=[],
                carryover_decisions=[],
            ),
        )
        self.assertEqual("closed", closed["status"])
        self.assertEqual("success", closed["closeout"]["founder_outcome"])

        with self.assertRaises(HTTPException) as exc:
            initiatives.get_initiative("init_missing")
        self.assertEqual(404, exc.exception.status_code)

    def test_linked_sessions_and_delegated_tasks_routes(self):
        from server.api.routes import initiatives
        from server.api.schemas import InitiativeCreateRequest, InitiativeLinkRequest

        created = initiatives.create_initiative(
            InitiativeCreateRequest(
                title="Coordinate launch evidence",
                objective="Keep board sessions and delegated tasks tied to launch work.",
            )
        )

        initiatives.create_link(
            created["id"],
            InitiativeLinkRequest(
                target_type="board_session",
                target_id="board_session_123",
                relationship="context",
            ),
        )

        self.assertEqual(
            {"initiative_id": created["id"], "session_ids": ["board_session_123"]},
            initiatives.list_initiative_sessions(created["id"]),
        )
        self.assertEqual(
            {"initiative_id": created["id"], "tasks": []},
            initiatives.list_initiative_tasks(created["id"]),
        )

        execution_store.save_delegated_task(
            {
                "id": "task_launch_evidence",
                "title": "Collect launch evidence",
                "objective": "Gather the board evidence packet.",
                "session_id": "board_session_123",
                "initiative_id": created["id"],
                "execution_unit_id": "engineering",
                "manager_agent_id": "technical_lead",
            }
        )

        tasks_response = initiatives.list_initiative_tasks(created["id"])
        self.assertEqual(created["id"], tasks_response["initiative_id"])
        self.assertEqual(["task_launch_evidence"], [task["id"] for task in tasks_response["tasks"]])

        with self.assertRaises(HTTPException) as exc:
            initiatives.list_initiative_sessions("init_missing")
        self.assertEqual(404, exc.exception.status_code)

        with self.assertRaises(HTTPException) as exc:
            initiatives.list_initiative_tasks("init_missing")
        self.assertEqual(404, exc.exception.status_code)

    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)
        self._previous_db_path = initiative_store._DEFAULT_DB_PATH
        self._previous_execution_db_path = execution_store._DEFAULT_DB_PATH
        initiative_store._DEFAULT_DB_PATH = self.tmp_path / "ledger.db"
        execution_store._DEFAULT_DB_PATH = self.tmp_path / "ledger.db"

    def tearDown(self):
        initiative_store._DEFAULT_DB_PATH = self._previous_db_path
        execution_store._DEFAULT_DB_PATH = self._previous_execution_db_path
        self._tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
