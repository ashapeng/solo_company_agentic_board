"""Verify that one live discussion produces exactly one Secretary brief."""

import unittest
from unittest.mock import patch

from server.board.deliberation.live import LiveBoardConversation
from server.board.deliberation.orchestrator import BoardSession


class LiveSecretarySingleBriefTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_secretary_starting_event_emitted_per_turn(self) -> None:
        """secretary_starting/_delta/_done must fire ONCE per round, not per turn."""
        events: list[dict] = []

        def capture(event):
            events.append(event)

        conversation = LiveBoardConversation(on_event=capture, max_turns=3)

        # Patch _stream_member_message and _produce_live_secretary_brief to fast-stub
        # the inner loop without LLM calls.
        async def fake_member_msg(self_conv, member, **_kwargs):
            from server.board.deliberation.live import ConversationMessage
            return ConversationMessage(
                id=f"msg_{member.id}",
                turn_index=1,
                member_id=member.id,
                member_title=member.title,
                role="member",
                content=f"{member.title} weighs in.",
            )

        async def fake_secretary_brief(self_conv, *, session, user_query, messages, response_language, session_id, round_index):
            capture({"event": "secretary_done", "round_index": round_index})

        with patch.object(LiveBoardConversation, "_stream_member_message", new=fake_member_msg), \
             patch.object(LiveBoardConversation, "_produce_live_secretary_brief", new=fake_secretary_brief), \
             patch("server.board.deliberation.live.detect_shortcut", return_value=None):
            session = await conversation.discuss(
                "Should we ship X?",
                member_ids=["strategist", "architect", "critic"],
            )

        secretary_dones = [e for e in events if e.get("event") == "secretary_done"]
        self.assertEqual(
            len(secretary_dones), 1,
            f"expected exactly 1 secretary_done event in single-round meeting, got {len(secretary_dones)}: {secretary_dones}"
        )
        self.assertEqual(secretary_dones[0]["round_index"], 0)


class LiveContinuationTest(unittest.IsolatedAsyncioTestCase):
    async def test_discuss_with_existing_session_bumps_continuation_count(self) -> None:
        events: list[dict] = []

        def capture(event):
            events.append(event)

        conversation = LiveBoardConversation(on_event=capture, max_turns=2)

        async def fake_member_msg(self_conv, member, **_kwargs):
            from server.board.deliberation.live import ConversationMessage
            return ConversationMessage(
                id=f"msg_{member.id}_round{self_conv._current_round}",
                turn_index=1,
                member_id=member.id,
                member_title=member.title,
                role="member",
                content=f"{member.title} weighs in.",
            )

        async def fake_secretary_brief(self_conv, *, session, user_query, messages, response_language, session_id, round_index):
            from server.board.deliberation.orchestrator import MemberResponse
            session.secretary_briefs.append(MemberResponse(
                member_id="secretary", stage=4, content=f"brief r{round_index}",
                model="m", elapsed_seconds=0.1,
            ))
            capture({"event": "secretary_done", "round_index": round_index})

        with patch.object(LiveBoardConversation, "_stream_member_message", new=fake_member_msg), \
             patch.object(LiveBoardConversation, "_produce_live_secretary_brief", new=fake_secretary_brief), \
             patch("server.board.deliberation.live.detect_shortcut", return_value=None):
            # Round 0
            session = await conversation.discuss(
                "Should we ship X?",
                member_ids=["strategist", "architect"],
            )
            self.assertEqual(session.continuation_count, 0)
            self.assertEqual(len(session.secretary_briefs), 1)

            # Round 1 — continuation
            await conversation.discuss(
                "Follow-up: what about pricing?",
                member_ids=["strategist", "architect"],
                existing_session=session,
            )
            self.assertEqual(session.continuation_count, 1)
            self.assertEqual(len(session.secretary_briefs), 2)

    async def test_discuss_emits_meeting_capped_when_at_max_continuations(self) -> None:
        import os
        os.environ["AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS"] = "1"
        try:
            events: list[dict] = []
            conversation = LiveBoardConversation(on_event=events.append, max_turns=1)

            async def fake_member_msg(self_conv, member, **_kwargs):
                from server.board.deliberation.live import ConversationMessage
                return ConversationMessage(id="m", turn_index=1, member_id=member.id,
                                          member_title=member.title, role="member", content="x")

            async def fake_secretary_brief(self_conv, **kwargs):
                pass

            with patch.object(LiveBoardConversation, "_stream_member_message", new=fake_member_msg), \
                 patch.object(LiveBoardConversation, "_produce_live_secretary_brief", new=fake_secretary_brief), \
                 patch("server.board.deliberation.live.detect_shortcut", return_value=None):
                session = await conversation.discuss("Q1", member_ids=["strategist"])
                # Force continuation count to the cap so the next call rejects.
                session.continuation_count = 1
                await conversation.discuss(
                    "Q2", member_ids=["strategist"], existing_session=session,
                )

            capped = [e for e in events if e.get("event") == "meeting_capped"]
            self.assertEqual(len(capped), 1)
            self.assertEqual(capped[0]["max_continuations"], 1)
        finally:
            os.environ.pop("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS", None)


if __name__ == "__main__":
    unittest.main()
