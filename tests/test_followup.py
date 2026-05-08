"""FollowupBuffer + parser tests."""
from __future__ import annotations

import asyncio

import pytest

from server.board.deliberation.followup import (
    Followup, FollowupBuffer, parse_followup_line,
)


def test_parse_followup_with_target():
    f = parse_followup_line("strategist: search more on Indian agencies")
    assert f is not None
    assert f.target == "strategist"
    assert f.text == "search more on Indian agencies"


def test_parse_followup_lowercases_target():
    f = parse_followup_line("Strategist: x")
    assert f.target == "strategist"


def test_parse_followup_unrouted():
    f = parse_followup_line("just a thought without a target")
    assert f is not None
    assert f.target is None
    assert f.text == "just a thought without a target"


def test_parse_followup_empty_returns_none():
    assert parse_followup_line("") is None
    assert parse_followup_line("   ") is None


async def test_buffer_add_and_take():
    buf = FollowupBuffer()
    await buf.add(Followup(target="strategist", text="x", raw="strategist: x"))
    await buf.add(Followup(target="researcher", text="y", raw="researcher: y"))
    s = await buf.take_for_member("strategist")
    assert len(s) == 1
    assert s[0].target == "strategist"
    r = await buf.take_for_member("researcher")
    assert len(r) == 1
    assert await buf.is_empty()


async def test_buffer_unrouted_collection():
    buf = FollowupBuffer()
    await buf.add(Followup(target=None, text="x", raw="x"))
    await buf.add(Followup(target="critic", text="y", raw="critic: y"))
    unrouted = await buf.take_unrouted()
    assert len(unrouted) == 1
    assert unrouted[0].target is None
    # Critic still in buffer
    rem = await buf.take_for_member("critic")
    assert len(rem) == 1


async def test_buffer_concurrent_safe():
    buf = FollowupBuffer()

    async def producer(prefix: str) -> None:
        for i in range(5):
            await buf.add(Followup(target=prefix, text=str(i), raw=f"{prefix}: {i}"))
            await asyncio.sleep(0)

    await asyncio.gather(producer("a"), producer("b"))
    a = await buf.take_for_member("a")
    b = await buf.take_for_member("b")
    assert len(a) == 5
    assert len(b) == 5
