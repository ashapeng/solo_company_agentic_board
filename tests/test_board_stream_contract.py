import json
import unittest

from starlette.requests import Request

from server.api import QueryRequest
from server.api.routes import board as board_routes


class BoardStreamContractTest(unittest.IsolatedAsyncioTestCase):
    def tearDown(self):
        board_routes._DELIBERATE_REQUESTS.clear()

    async def test_member_done_event_includes_response_content(self):
        fake_request = Request({
            "type": "http",
            "method": "POST",
            "path": "/deliberate/stream",
            "headers": [],
            "client": ("127.0.0.1", 9999),
        })

        class FakeMember:
            id = "strategist"
            title = "Chief Strategist"

        class FakeResponse:
            model = "test-model"
            elapsed_seconds = 0.2
            content = "### Recommendation\nRun a concierge MVP."

        class FakeSession:
            def to_dict(self):
                return {"session_id": "board_stream", "user_query": "Should we build this?"}

        class FakeOrchestrator:
            def __init__(self, **callbacks):
                self.callbacks = callbacks

            async def deliberate(self, *args, **kwargs):
                self.callbacks["on_member_done"](1, FakeMember(), FakeResponse())
                return FakeSession()

        original = board_routes.BoardOrchestrator
        board_routes.BoardOrchestrator = FakeOrchestrator
        try:
            response = await board_routes.deliberate_stream(
                QueryRequest(query="Should we build this?"),
                fake_request,
            )
            chunks: list[str] = []
            async for chunk in response.body_iterator:
                chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        finally:
            board_routes.BoardOrchestrator = original

        events = [
            json.loads(line.removeprefix("data: "))
            for chunk in chunks
            for line in chunk.splitlines()
            if line.startswith("data: ")
        ]
        member_done = next(event for event in events if event["event"] == "member_done")

        self.assertEqual("### Recommendation\nRun a concierge MVP.", member_done["content"])


if __name__ == "__main__":
    unittest.main()
