import feedparser

from server.discovery.channels.rss import RssChannel

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>BC Bid</title>
<item>
  <title>New tender: signage design services</title>
  <link>https://example.gov/tender/1</link>
  <guid>tender-1</guid>
  <description>Design services for provincial signage program</description>
  <pubDate>Tue, 01 Jul 2026 10:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_fetch_maps_entries():
    ch = RssChannel(parse=lambda url: feedparser.parse(RSS_XML))
    posts = ch.fetch({"url": "https://example.gov/feed", "label": "bcbid"})
    p = posts[0]
    assert p.id == "tender-1"
    assert p.channel == "rss"
    assert p.source == "bcbid"
    assert p.title.startswith("New tender")
    assert "signage" in p.body
    assert p.url == "https://example.gov/tender/1"


def test_fetch_bozo_feed_raises():
    ch = RssChannel(parse=lambda url: feedparser.parse("not xml at all <<<"))
    try:
        ch.fetch({"url": "https://bad", "label": "bad"})
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_health_is_ok_without_network():
    assert RssChannel().health().status == "ok"
