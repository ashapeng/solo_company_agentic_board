import httpx
import pytest

from server.discovery.http_safety import DiscoveryHttpStop, SafeHttpClient


def test_retries_transient_and_honors_retry_after():
    statuses = iter([503, 200])
    sleeps = []

    def handler(request):
        status = next(statuses)
        return httpx.Response(
            status,
            headers={"Retry-After": "2"} if status == 503 else {},
            json={"ok": True},
        )

    client = SafeHttpClient(
        transport=httpx.MockTransport(handler), sleep=sleeps.append, jitter=lambda a, b: 0
    )
    assert client.get("https://example.com/data").json() == {"ok": True}
    assert sleeps == [2.0]


@pytest.mark.parametrize("status", [401, 403, 429])
def test_stops_without_retry_on_access_or_rate_gate(status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status)

    client = SafeHttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    with pytest.raises(DiscoveryHttpStop, match=str(status)):
        client.get("https://example.com/data")
    assert len(calls) == 1


def test_stops_on_captcha_and_daily_ceiling():
    challenge = SafeHttpClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, headers={"content-type": "text/html"}, text="Verify you are human CAPTCHA"
            )
        )
    )
    with pytest.raises(DiscoveryHttpStop, match="CAPTCHA"):
        challenge.get("https://example.com/data")

    client = SafeHttpClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        daily_request_ceiling=1,
    )
    client.get("https://example.com/one")
    with pytest.raises(DiscoveryHttpStop, match="daily request ceiling"):
        client.get("https://example.com/two")


def test_sets_honest_stable_user_agent():
    seen = []

    def handler(request):
        seen.append(request.headers["user-agent"])
        return httpx.Response(200)

    SafeHttpClient(transport=httpx.MockTransport(handler)).get("https://example.com")
    assert seen[0].startswith("agentic-board-discovery/")
