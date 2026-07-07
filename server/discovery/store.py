from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from server.discovery.channels.base import RawPost


def iso_week() -> str:
    return datetime.now(tz=timezone.utc).strftime("%G-W%V")


class DiscoveryStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._seen_path = self.root / "seen_ids.json"

    def _load_seen(self) -> set[str]:
        if not self._seen_path.exists():
            return set()
        return set(json.loads(self._seen_path.read_text(encoding="utf-8")))

    def filter_new(self, posts: list[RawPost]) -> list[RawPost]:
        seen = self._load_seen()
        return [p for p in posts if p.key() not in seen]

    def mark_seen(self, posts: list[RawPost]) -> None:
        seen = self._load_seen()
        seen.update(p.key() for p in posts)
        self._seen_path.write_text(json.dumps(sorted(seen)), encoding="utf-8")

    def write_raw(self, week: str, channel: str, label: str, posts: list[RawPost]) -> Path:
        week_dir = self.root / "raw" / week
        week_dir.mkdir(parents=True, exist_ok=True)
        path = week_dir / f"{channel}-{label}.json"
        path.write_text(
            json.dumps([asdict(p) for p in posts], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def write_manifest(self, week: str, manifest: dict) -> Path:
        week_dir = self.root / "raw" / week
        week_dir.mkdir(parents=True, exist_ok=True)
        path = week_dir / "manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def read_manifest(self, week: str) -> dict | None:
        path = self.root / "raw" / week / "manifest.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def latest_manifest(self) -> tuple[str, dict] | None:
        raw_dir = self.root / "raw"
        if not raw_dir.exists():
            return None
        weeks = sorted(d.name for d in raw_dir.iterdir() if (d / "manifest.json").exists())
        if not weeks:
            return None
        week = weeks[-1]
        return week, self.read_manifest(week)
