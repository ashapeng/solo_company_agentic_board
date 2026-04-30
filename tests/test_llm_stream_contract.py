import unittest
from unittest.mock import AsyncMock, patch

from server.board.llm import LLMResponse, LLMStreamChunk


class LLMStreamContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_query_llm_stream_fallback_emits_deltas_before_final_metadata(self):
        from server.board.llm import query_llm_stream

        response = LLMResponse(
            content="Alpha beta gamma delta.",
            model="test-model",
            input_tokens=11,
            output_tokens=4,
            latency_seconds=0.2,
            finish_reason="stop",
            response_id="resp_1",
        )

        with patch("server.board.llm.query_llm", new=AsyncMock(return_value=response)):
            chunks = [
                chunk async for chunk in query_llm_stream(
                    "test/model",
                    [{"role": "user", "content": "Say something."}],
                    max_tokens=64,
                )
            ]

        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(any(chunk.delta for chunk in chunks[:-1]))
        self.assertTrue(chunks[-1].done)
        self.assertEqual("Alpha beta gamma delta.", chunks[-1].content)
        self.assertEqual(11, chunks[-1].input_tokens)
        self.assertEqual(4, chunks[-1].output_tokens)
        self.assertTrue(chunks[-1].simulated_stream)

    async def test_query_llm_stream_uses_native_handler_for_registered_prefix(self):
        from server.board import llm
        from server.board.llm import query_llm_stream

        async def fake_stream_handler(*args, **kwargs):
            yield LLMStreamChunk(delta="native ", content="native ", model="deepseek/test")
            yield LLMStreamChunk(
                content="native stream",
                done=True,
                model="deepseek/test",
                finish_reason="stop",
                simulated_stream=False,
            )

        with patch.dict(llm._STREAM_HANDLERS, {"deepseek": fake_stream_handler}, clear=True):
            chunks = [
                chunk async for chunk in query_llm_stream(
                    "deepseek/test",
                    [{"role": "user", "content": "Say something."}],
                    max_tokens=64,
                )
            ]

        self.assertEqual("native ", chunks[0].delta)
        self.assertTrue(chunks[-1].done)
        self.assertFalse(chunks[-1].simulated_stream)


if __name__ == "__main__":
    unittest.main()
