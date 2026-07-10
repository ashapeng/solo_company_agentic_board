import json

from server.discovery.channels.github import GitHubChannel

GH_ISSUES = json.dumps(
    [
        {
            "title": "Inventory tracking for craft supplies is unusable",
            "body": "I have 400 yarn SKUs and this tool chokes",
            "url": "https://github.com/org/repo/issues/12",
            "repository": {"nameWithOwner": "org/repo"},
            "commentsCount": 23,
            "createdAt": "2026-07-01T10:00:00Z",
            "author": {"login": "yarnhoarder"},
        }
    ]
)


def fake_runner(args):
    if args[:2] == ["auth", "status"]:
        return "Logged in to github.com"
    return GH_ISSUES


def test_fetch_maps_issues():
    ch = GitHubChannel(runner=fake_runner)
    posts = ch.fetch({"query": "crafts inventory", "search": "issues", "label": "crafts"})
    p = posts[0]
    assert p.id == "https://github.com/org/repo/issues/12"
    assert p.channel == "github"
    assert p.source == "org/repo"
    assert p.comments == 23
    assert p.author == "yarnhoarder"


def test_health_unconfigured_without_auth():
    def no_auth(args):
        raise FileNotFoundError("gh not found")

    assert GitHubChannel(runner=no_auth).health().status == "unconfigured"
