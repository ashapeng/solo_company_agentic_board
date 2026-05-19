"""Contract tests for BoardSession multi-round fields."""

import asyncio
import unittest

from server.board.projection import adapt_session_record
from server.board.deliberation.orchestrator import BoardSession, MemberResponse


class BoardSessionShapeTest(unittest.TestCase):
    def test_default_continuation_count_is_zero(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        self.assertEqual(session.continuation_count, 0)

    def test_default_secretary_briefs_is_empty_list(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        self.assertEqual(session.secretary_briefs, [])

    def test_secretary_brief_alias_returns_last_brief(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        first = MemberResponse(member_id="secretary", stage=4, content="round 0 brief", model="m", elapsed_seconds=0.1)
        second = MemberResponse(member_id="secretary", stage=4, content="round 1 brief", model="m", elapsed_seconds=0.1)
        session.secretary_briefs.append(first)
        self.assertIs(session.secretary_brief, first)
        session.secretary_briefs.append(second)
        self.assertIs(session.secretary_brief, second)

    def test_secretary_brief_alias_returns_none_when_empty(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        self.assertIsNone(session.secretary_brief)

    def test_to_dict_serializes_continuation_count_and_briefs(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        session.continuation_count = 2
        session.secretary_briefs.append(
            MemberResponse(member_id="secretary", stage=4, content="b", model="m", elapsed_seconds=0.1)
        )
        as_dict = session.to_dict()
        self.assertEqual(as_dict["continuation_count"], 2)
        self.assertEqual(len(as_dict["secretary_briefs"]), 1)
        self.assertEqual(as_dict["secretary_briefs"][0]["content"], "b")
        # Back-compat: secretary_brief still surfaces the latest entry.
        self.assertEqual(as_dict["secretary_brief"]["content"], "b")

    def test_to_dict_serializes_initiative_fields(self) -> None:
        session = BoardSession(
            session_id="board_1",
            user_query="Q",
            initiative_id="init_123",
            initiative_mode="attach",
        )

        as_dict = session.to_dict()

        self.assertEqual(as_dict["initiative_id"], "init_123")
        self.assertEqual(as_dict["initiative_mode"], "attach")

    def test_projection_exposes_initiative_fields_with_default_mode(self) -> None:
        projected = adapt_session_record({
            "session_id": "board_1",
            "user_query": "Q",
            "initiative_id": "init_123",
        })

        self.assertEqual(projected["initiative_id"], "init_123")
        self.assertEqual(projected["initiative_mode"], "ad_hoc")

    def test_live_existing_session_applies_missing_initiative_fields(self) -> None:
        from server.board.deliberation.live import LiveBoardConversation

        session = BoardSession(session_id="board_3", user_query="Q")
        conversation = LiveBoardConversation(max_turns=1)
        session.continuation_count = conversation.max_continuations

        resumed = asyncio.run(conversation.discuss(
            "continue",
            existing_session=session,
            initiative_id="init_123",
            initiative_mode="attach",
        ))

        self.assertEqual(resumed.initiative_id, "init_123")
        self.assertEqual(resumed.initiative_mode, "attach")

    def test_live_existing_session_preserves_existing_initiative_fields(self) -> None:
        from server.board.deliberation.live import LiveBoardConversation

        session = BoardSession(
            session_id="board_4",
            user_query="Q",
            initiative_id="init_existing",
            initiative_mode="attach",
        )
        conversation = LiveBoardConversation(max_turns=1)
        session.continuation_count = conversation.max_continuations

        resumed = asyncio.run(conversation.discuss(
            "continue",
            existing_session=session,
            initiative_id="init_other",
            initiative_mode="create_draft",
        ))

        self.assertEqual(resumed.initiative_id, "init_existing")
        self.assertEqual(resumed.initiative_mode, "attach")

    def test_status_can_be_adjourned(self) -> None:
        session = BoardSession(session_id="board_1", user_query="Q")
        session.status = "adjourned"
        self.assertEqual(session.status, "adjourned")
        self.assertEqual(session.to_dict()["status"], "adjourned")


if __name__ == "__main__":
    unittest.main()
