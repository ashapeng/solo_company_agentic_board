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


if __name__ == "__main__":
    unittest.main()
