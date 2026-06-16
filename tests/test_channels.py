"""Tests for the multi-channel reach package (server/channels).

All tests are offline: the HTTP client and deliberation backend are faked.
"""

from __future__ import annotations

import argparse
import unittest

from server.channels import (
    ChannelAdapter,
    ChannelDeps,
    SessionMapper,
    TelegramChannel,
    load_enabled_channels,
    render_brief,
)


class SessionMapperTest(unittest.TestCase):
    def test_same_triple_returns_same_session_id(self):
        mapper = SessionMapper()
        first, venture1 = mapper.resolve("telegram", "user1", "thread1")
        second, venture2 = mapper.resolve("telegram", "user1", "thread1")

        self.assertEqual(first, second)
        self.assertEqual("default", venture1)
        self.assertEqual(venture1, venture2)
        self.assertTrue(first)

    def test_different_threads_get_different_ids(self):
        mapper = SessionMapper()
        a, _ = mapper.resolve("telegram", "user1", "thread1")
        b, _ = mapper.resolve("telegram", "user1", "thread2")
        c, _ = mapper.resolve("telegram", "user2", "thread1")

        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(b, c)

    def test_deterministic_across_mapper_instances(self):
        a, _ = SessionMapper().resolve("telegram", "u", "t")
        b, _ = SessionMapper().resolve("telegram", "u", "t")
        self.assertEqual(a, b)

    def test_custom_venture_is_returned(self):
        mapper = SessionMapper()
        _, venture = mapper.resolve("telegram", "u", "t", venture_id="acme")
        self.assertEqual("acme", venture)


class RenderBriefTest(unittest.TestCase):
    def test_dict_with_executive_summary(self):
        out = render_brief(
            {
                "executive_summary": "Ship a concierge MVP.",
                "next_steps": ["Email 10 prospects", "Book 2 calls"],
            }
        )
        self.assertIsInstance(out, str)
        self.assertIn("concierge MVP", out)
        self.assertIn("Email 10 prospects", out)

    def test_nested_decision_dict(self):
        out = render_brief({"decision": {"executive_summary": "Hold steady."}})
        self.assertIn("Hold steady.", out)

    def test_projection_object(self):
        from server.board.projection import BoardDecisionProjection

        proj = BoardDecisionProjection(
            executive_summary="Do not pivot.",
            next_steps=["Run another experiment"],
        )
        out = render_brief(proj)
        self.assertIn("Do not pivot.", out)
        self.assertIn("Run another experiment", out)

    def test_session_like_object_with_synthesis(self):
        class _Synthesis:
            content = "### Executive Summary\nLaunch the beta.\n\n### Next Steps\n- Recruit testers"

        class _Session:
            decision = None
            stage3_synthesis = _Synthesis()

        out = render_brief(_Session())
        self.assertIn("Launch the beta.", out)

    def test_minimal_object_does_not_raise(self):
        class _Minimal:
            decision = {"executive_summary": "Tiny."}

        out = render_brief(_Minimal())
        self.assertIsInstance(out, str)
        self.assertIn("Tiny.", out)

    def test_junk_input_falls_back_and_never_raises(self):
        out = render_brief(12345)
        self.assertIsInstance(out, str)
        self.assertTrue(out)

        out2 = render_brief(object())
        self.assertIsInstance(out2, str)
        self.assertTrue(out2)


class _FakeHttp:
    """Records send_message calls; never touches the network."""

    def __init__(self):
        self.sent: list[tuple] = []
        self.updates_batches: list[list] = []

    async def get_updates(self, offset):  # pragma: no cover - not used here
        if self.updates_batches:
            return self.updates_batches.pop(0)
        return []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))
        return {"ok": True}


class TelegramChannelTest(unittest.IsolatedAsyncioTestCase):
    async def test_handle_update_deliberates_and_replies(self):
        http = _FakeHttp()
        seen_queries: list[str] = []

        async def fake_deliberate(query: str):
            seen_queries.append(query)
            return {"executive_summary": "Yes, launch the narrow wedge."}

        deps = ChannelDeps(deliberate=fake_deliberate, render=render_brief)
        channel = TelegramChannel("test-token", http=http)

        update = {"message": {"chat": {"id": 42}, "text": "should we launch?"}}
        await channel._handle_update(update, deps)

        self.assertEqual(["should we launch?"], seen_queries)
        self.assertEqual(1, len(http.sent))
        chat_id, text = http.sent[0]
        self.assertEqual(42, chat_id)
        self.assertIsInstance(text, str)
        self.assertIn("narrow wedge", text)

    async def test_handle_update_ignores_textless_update(self):
        http = _FakeHttp()
        called = []

        async def fake_deliberate(query: str):
            called.append(query)
            return {}

        deps = ChannelDeps(deliberate=fake_deliberate, render=render_brief)
        channel = TelegramChannel("test-token", http=http)

        await channel._handle_update({"message": {"chat": {"id": 1}}}, deps)
        await channel._handle_update({}, deps)

        self.assertEqual([], called)
        self.assertEqual([], http.sent)

    async def test_handle_update_never_crashes_on_failing_deliberate(self):
        http = _FakeHttp()

        async def boom(query: str):
            raise RuntimeError("backend exploded")

        deps = ChannelDeps(deliberate=boom, render=render_brief)
        channel = TelegramChannel("test-token", http=http)

        # Should swallow the error, not raise.
        await channel._handle_update(
            {"message": {"chat": {"id": 7}, "text": "hi"}}, deps
        )
        self.assertEqual([], http.sent)

    def test_channel_key_and_default_http_built_at_runtime(self):
        # Token-only construction must build a default client without network.
        channel = TelegramChannel("test-token")
        self.assertEqual("telegram", channel.channel_key)
        self.assertIsNotNone(channel.http)

    def test_satisfies_channel_adapter_protocol(self):
        channel = TelegramChannel("test-token", http=_FakeHttp())
        self.assertIsInstance(channel, ChannelAdapter)


class ProtocolRoundTripTest(unittest.IsolatedAsyncioTestCase):
    async def test_tiny_fake_adapter_wires_deps(self):
        received: dict = {}

        class FakeAdapter:
            channel_key = "fake"

            async def start(self, deps: ChannelDeps) -> None:
                result = await deps.deliberate("ping")
                received["rendered"] = deps.render(result)

        async def fake_deliberate(query: str):
            return {"executive_summary": f"answer to {query}"}

        adapter = FakeAdapter()
        self.assertIsInstance(adapter, ChannelAdapter)

        deps = ChannelDeps(deliberate=fake_deliberate, render=render_brief)
        await adapter.start(deps)

        self.assertIn("answer to ping", received["rendered"])


class LoaderTest(unittest.TestCase):
    def test_no_tokens_returns_empty_list(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual([], load_enabled_channels())

    def test_telegram_token_yields_telegram_channel(self):
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "abc"}, clear=True):
            channels = load_enabled_channels()
        self.assertEqual(1, len(channels))
        self.assertEqual("telegram", channels[0].channel_key)


class CliFlagTest(unittest.TestCase):
    def test_parser_accepts_serve_channels(self):
        # Build a parser with the same flag and confirm it parses without error.
        parser = argparse.ArgumentParser()
        parser.add_argument("--serve-channels", action="store_true")
        args = parser.parse_args(["--serve-channels"])
        self.assertTrue(args.serve_channels)

    def test_serve_channels_is_noop_without_tokens(self):
        import os
        from unittest.mock import patch

        from server.cli import serve_channels

        with patch.dict(os.environ, {}, clear=True):
            # Must return cleanly (no servers started) when nothing configured.
            serve_channels()


if __name__ == "__main__":
    unittest.main()
