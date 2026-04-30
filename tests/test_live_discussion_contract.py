import json
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from starlette.requests import Request

from server.api import QueryRequest
from server.api.routes import board as board_routes
from server.board.deliberation.orchestrator import BoardSession


class LiveDiscussionContractTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        board_routes._DELIBERATE_REQUESTS.clear()

    async def test_live_stream_emits_delta_before_message_done(self):
        fake_request = Request({
            "type": "http",
            "method": "POST",
            "path": "/deliberate/stream",
            "headers": [],
            "client": ("127.0.0.1", 9999),
        })

        class FakeLiveConversation:
            def __init__(self, *, on_event=None):
                self.on_event = on_event

            async def discuss(self, *args, **kwargs):
                self.on_event({
                    "event": "conversation_started",
                    "session_id": "board_1",
                    "member_ids": ["strategist"],
                    "chairman_id": "chairperson",
                })
                self.on_event({
                    "event": "message_start",
                    "message_id": "msg_1",
                    "turn_index": 1,
                    "member_id": "strategist",
                    "member_title": "Chief Strategist",
                })
                self.on_event({
                    "event": "message_delta",
                    "message_id": "msg_1",
                    "turn_index": 1,
                    "member_id": "strategist",
                    "delta": "We should validate ",
                    "content": "We should validate ",
                })
                self.on_event({
                    "event": "message_done",
                    "message_id": "msg_1",
                    "turn_index": 1,
                    "member_id": "strategist",
                    "member_title": "Chief Strategist",
                    "content": "We should validate demand.",
                    "finish_reason": "stop",
                })
                session = BoardSession(session_id="board_1", user_query="Should we build this?")
                session.conversation = {
                    "messages": [{
                        "id": "msg_1",
                        "member_id": "strategist",
                        "content": "We should validate demand.",
                    }],
                    "routing_trace": [],
                }
                return session

        original = board_routes.LiveBoardConversation
        board_routes.LiveBoardConversation = FakeLiveConversation
        try:
            response = await board_routes.deliberate_stream(
                QueryRequest(query="Should we build this?", discussion_mode="live"),
                fake_request,
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        finally:
            board_routes.LiveBoardConversation = original

        events = [
            json.loads(line.removeprefix("data: "))
            for chunk in chunks
            for line in chunk.splitlines()
            if line.startswith("data: ")
        ]
        event_names = [event["event"] for event in events]

        self.assertLess(event_names.index("message_delta"), event_names.index("message_done"))
        self.assertIn("complete", event_names)

    def test_router_selects_researcher_when_strategy_mentions_customer_research(self):
        from server.board.deliberation.live import ConversationMessage, route_next_speaker
        from server.board.config import get_board_members

        members = get_board_members()
        council = [member for member in members if member.id in {"strategist", "researcher", "product"}]
        prior = ConversationMessage(
            id="msg_1",
            turn_index=1,
            member_id="strategist",
            member_title="Chief Strategist",
            role="Market Strategy",
            content=(
                "The market looks plausible, but the next immediate gap is customer research: "
                "we need interviews and observed behavior before deciding."
            ),
        )

        decision = route_next_speaker(
            council,
            chairperson=next(member for member in members if member.id == "chairperson"),
            messages=[prior],
            used_member_ids={"strategist"},
            turn_index=2,
            max_turns=5,
        )

        self.assertEqual("researcher", decision.member_id)
        self.assertEqual("customer_research", decision.trigger)

    def test_router_stops_for_ceo_decision_instead_of_auto_chair(self):
        from server.board.deliberation.live import ConversationMessage, route_next_speaker
        from server.board.config import get_board_members

        members = get_board_members()
        council = [member for member in members if member.id in {"strategist", "researcher"}]
        prior = ConversationMessage(
            id="msg_1",
            turn_index=1,
            member_id="researcher",
            member_title="Customer Researcher",
            role="Customer Research",
            content="We have enough inputs for the CEO to decide.",
        )

        decision = route_next_speaker(
            council,
            chairperson=next(member for member in members if member.id == "chairperson"),
            messages=[prior],
            used_member_ids={"strategist", "researcher"},
            turn_index=3,
            max_turns=5,
        )

        self.assertIsNone(decision.member_id)
        self.assertEqual("awaiting_ceo_decision", decision.trigger)

    def test_chinese_query_adds_chinese_only_response_instruction(self):
        from server.board.config import get_board_members
        from server.board.deliberation.live import (
            TurnDecision,
            _format_live_prompt,
            _live_system_prompt,
        )

        member = next(member for member in get_board_members() if member.id == "strategist")
        prompt = _format_live_prompt(
            member=member,
            user_query="请帮我判断这个产品方向是否值得做",
            messages=[],
            decision=TurnDecision(
                member_id="strategist",
                trigger="initial_route",
                routing_reason="Initial speaker.",
                reply_to_message_id="user_0",
            ),
            is_chair=False,
        )
        system = _live_system_prompt(member, user_query="请帮我判断这个产品方向是否值得做")

        self.assertIn("简体中文", prompt)
        self.assertIn("简体中文", system)
        self.assertIn("不要中英混杂", system)

    async def test_live_member_message_continues_when_provider_hits_length(self):
        from server.board.config import get_board_members
        from server.board.deliberation.live import (
            LiveBoardConversation,
            TurnDecision,
        )
        from server.board.llm import LLMStreamChunk

        members = get_board_members()
        critic = next(member for member in members if member.id == "critic")
        events: list[dict] = []
        calls: list[list[dict[str, str]]] = []

        async def fake_stream(model, messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                yield LLMStreamChunk(
                    delta="好的，我们先把失败倒过来看。",
                    content="好的，我们先把失败倒过来看。",
                    model=model,
                )
                yield LLMStreamChunk(
                    content="好的，我们先把失败倒过来看。",
                    done=True,
                    model=model,
                    finish_reason="length",
                )
                return

            self.assertIn("继续", messages[-1]["content"])
            yield LLMStreamChunk(
                delta="补完整：这个方向只有在真实付费信号出现后才值得推进。",
                content="补完整：这个方向只有在真实付费信号出现后才值得推进。",
                model=model,
            )
            yield LLMStreamChunk(
                content="补完整：这个方向只有在真实付费信号出现后才值得推进。",
                done=True,
                model=model,
                finish_reason="stop",
            )

        conversation = LiveBoardConversation(
            members=members,
            on_event=events.append,
            max_turns=1,
        )
        decision = TurnDecision(
            member_id="critic",
            trigger="risk_challenge",
            routing_reason="The thread needs explicit assumption pressure and dissent.",
            reply_to_message_id="msg_1",
        )

        with patch("server.board.deliberation.live.query_llm_stream", fake_stream):
            message = await conversation._stream_member_message(
                critic,
                user_query="请判断这个方向",
                messages=[],
                decision=decision,
                turn_index=2,
                query_type=None,
                complexity=None,
                response_language="zh",
                session_id="board_test",
            )

        self.assertEqual(2, len(calls))
        self.assertEqual(
            "好的，我们先把失败倒过来看。补完整：这个方向只有在真实付费信号出现后才值得推进。",
            message.content,
        )
        self.assertEqual("stop", message.finish_reason)
        event_names = [event["event"] for event in events]
        self.assertEqual(1, event_names.count("message_done"))
        self.assertLess(event_names.index("message_delta"), event_names.index("message_done"))

    def test_board_session_preserves_full_conversation_content(self):
        long_content = "Customer discovery says keep the complete message. " * 60
        session = BoardSession(session_id="board_2", user_query="Should we build this?")
        session.conversation = {
            "messages": [{
                "id": "msg_1",
                "turn_index": 1,
                "member_id": "researcher",
                "member_title": "Customer Researcher",
                "content": long_content,
            }],
            "routing_trace": [],
        }

        payload = session.to_dict()

        self.assertEqual(long_content, payload["conversation"]["messages"][0]["content"])

    def test_query_request_defaults_to_staged_mode(self):
        req = QueryRequest(query="Should we build this?")

        self.assertEqual("staged", req.discussion_mode)


if __name__ == "__main__":
    unittest.main()
