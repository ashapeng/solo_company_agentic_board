from __future__ import annotations

import json
import subprocess

from server.discovery.channels.base import ChannelHealth, RawPost


def _default_runner(args: list[str]) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=True, timeout=120
    )
    return result.stdout


class GitHubChannel:
    name = "github"

    def __init__(self, runner=None):
        self._run = runner or _default_runner

    def fetch(self, item: dict) -> list[RawPost]:
        kind = item.get("search", "issues")
        try:
            stdout = self._run(
                [
                    "search",
                    kind,
                    item["query"],
                    "--json",
                    "title,body,url,repository,commentsCount,createdAt,author",
                    "--limit",
                    "50",
                ]
            )
        except FileNotFoundError as exc:
            raise RuntimeError("gh CLI not installed or not on PATH") from exc
        posts = []
        for row in json.loads(stdout):
            posts.append(
                RawPost(
                    id=row["url"],
                    channel=self.name,
                    source=(row.get("repository") or {}).get("nameWithOwner", ""),
                    title=row.get("title", ""),
                    body=(row.get("body") or "")[:4000],
                    url=row["url"],
                    author=(row.get("author") or {}).get("login", ""),
                    comments=int(row.get("commentsCount") or 0),
                    created_at=row.get("createdAt", ""),
                )
            )
        return posts

    def health(self) -> ChannelHealth:
        try:
            self._run(["auth", "status"])
            return ChannelHealth(self.name, "ok")
        except FileNotFoundError:
            return ChannelHealth(self.name, "unconfigured", "gh CLI missing")
        except Exception as exc:
            return ChannelHealth(
                self.name, "unconfigured", f"gh not authenticated: {exc}"
            )
