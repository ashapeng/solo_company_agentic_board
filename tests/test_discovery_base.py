from server.discovery.channels.base import RawPost, ChannelHealth, slugify


def test_rawpost_defaults():
    p = RawPost(id="x1", channel="fake", source="unit", title="t", body="b", url="http://u")
    assert p.author == ""
    assert p.score == 0
    assert p.comments == 0
    assert p.created_at == ""
    assert p.extra == {}


def test_rawpost_key():
    p = RawPost(id="x1", channel="fake", source="unit", title="t", body="b", url="http://u")
    assert p.key() == "fake:x1"


def test_channel_health():
    h = ChannelHealth(channel="reddit", status="ok")
    assert h.detail == ""


def test_slugify():
    assert slugify("Etsy shop problems!") == "etsy-shop-problems"
    assert slugify("r/knitting  TOP") == "r-knitting-top"
