from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone

from server.discovery.channels.base import ChannelHealth, RawPost


def _default_runner(args: list[str]) -> str:
    result = subprocess.run(
        ["yt-dlp", *args], capture_output=True, text=True, check=True, timeout=300
    )
    return result.stdout


class YouTubeChannel:
    name = "youtube"

    def __init__(self, runner=None):
        self._fixture_mode = runner is not None
        self._run = runner or _default_runner

    def fetch(self, item: dict) -> list[RawPost]:
        if not self._fixture_mode:
            raise RuntimeError(
                "youtube adapter is held: approved YouTube Data API replacement required"
            )
        max_videos = int(item.get("max_videos", 5))
        try:
            stdout = self._run(
                [f"ytsearch{max_videos}:{item['query']}", "--dump-json", "--flat-playlist", "--no-download"]
            )
        except FileNotFoundError as exc:
            raise RuntimeError("legacy held yt-dlp fixture runner is unavailable") from exc
        videos = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        posts = []
        for vid in videos:
            posts.append(
                RawPost(
                    id=str(vid["id"]),
                    channel=self.name,
                    source=item["query"],
                    title=vid.get("title", ""),
                    body=vid.get("description") or "",
                    url=vid.get("url") or f"https://www.youtube.com/watch?v={vid['id']}",
                    author=vid.get("channel", ""),
                    score=int(vid.get("view_count") or 0),
                )
            )
            if item.get("include_comments"):
                posts.extend(self._fetch_comments(vid))
        return posts

    def _fetch_comments(self, vid: dict) -> list[RawPost]:
        url = vid.get("url") or f"https://www.youtube.com/watch?v={vid['id']}"
        stdout = self._run(
            [
                url,
                "--skip-download",
                "--write-comments",
                "--dump-single-json",
                "--extractor-args",
                "youtube:max_comments=50",
            ]
        )
        detail = json.loads(stdout)
        posts = []
        for c in detail.get("comments") or []:
            ts = c.get("timestamp")
            posts.append(
                RawPost(
                    id=f"{vid['id']}:{c['id']}",
                    channel=self.name,
                    source=vid.get("title", ""),
                    title="",
                    body=c.get("text", ""),
                    url=url,
                    author=c.get("author", ""),
                    score=int(c.get("like_count") or 0),
                    created_at=(
                        datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if ts else ""
                    ),
                    extra={"video_title": detail.get("title", ""), "kind": "comment"},
                )
            )
        return posts

    def health(self) -> ChannelHealth:
        if not self._fixture_mode:
            return ChannelHealth(
                self.name,
                "held",
                "approved YouTube Data API replacement required",
                posture="held",
            )
        try:
            version = self._run(["--version"]).strip()
            return ChannelHealth(self.name, "ok", f"yt-dlp {version}")
        except FileNotFoundError:
            return ChannelHealth(
                self.name, "unconfigured", "legacy held yt-dlp fixture runner unavailable"
            )
        except Exception as exc:
            return ChannelHealth(self.name, "error", str(exc))
