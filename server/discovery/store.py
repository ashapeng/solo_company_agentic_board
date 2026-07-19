from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from server.discovery.channels.base import RawPost

if TYPE_CHECKING:
    from server.discovery.analyze.models import AgentBundle, TopicReport


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

    @staticmethod
    def _atomic_write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass
            raise
        return path

    def filter_new(self, posts: list[RawPost]) -> list[RawPost]:
        seen = self._load_seen()
        return [p for p in posts if p.key() not in seen]

    def mark_seen(self, posts: list[RawPost]) -> None:
        seen = self._load_seen()
        seen.update(p.key() for p in posts)
        self._atomic_write(self._seen_path, json.dumps(sorted(seen)))

    def write_raw(self, week: str, channel: str, label: str, posts: list[RawPost]) -> Path:
        week_dir = self.root / "raw" / week
        week_dir.mkdir(parents=True, exist_ok=True)
        path = week_dir / f"{channel}-{label}.json"
        return self._atomic_write(
            path, json.dumps([asdict(p) for p in posts], indent=2, ensure_ascii=False)
        )

    def write_manifest(self, week: str, manifest: dict) -> Path:
        week_dir = self.root / "raw" / week
        week_dir.mkdir(parents=True, exist_ok=True)
        path = week_dir / "manifest.json"
        return self._atomic_write(path, json.dumps(manifest, indent=2, ensure_ascii=False))

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

    def read_week_posts(self, week: str) -> list[RawPost]:
        week_dir = self.root / "raw" / week
        if not week_dir.exists():
            return []
        posts: list[RawPost] = []
        seen: dict[str, Path] = {}
        for path in sorted(week_dir.glob("*.json")):
            if path.name == "manifest.json":
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid discovery raw file {path}: {exc}") from exc
            if not isinstance(raw, list):
                raise ValueError(f"invalid discovery raw file {path}: root must be a list")
            for index, item in enumerate(raw):
                location = f"{path}[{index}]"
                if not isinstance(item, dict):
                    raise ValueError(f"invalid discovery raw record {location}: must be an object")
                try:
                    post = self._raw_post(item, location)
                except (TypeError, ValueError, KeyError) as exc:
                    raise ValueError(f"invalid discovery raw record {location}: {exc}") from exc
                key = post.key()
                if key in seen:
                    raise ValueError(
                        f"duplicate post_key {key!r} in {location}; first seen in {seen[key]}"
                    )
                seen[key] = path
                posts.append(post)
        return posts

    @staticmethod
    def _raw_post(item: dict[str, Any], location: str) -> RawPost:
        for field in ("id", "channel"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"{field} must be a non-empty string")
        text_fields: dict[str, str] = {}
        for field in ("source", "title", "body", "url", "author", "created_at"):
            value = item.get(field, item["channel"] if field == "source" else "")
            if not isinstance(value, str):
                raise ValueError(f"{field} must be a string")
            text_fields[field] = value
        numbers: dict[str, int] = {}
        for field in ("score", "comments"):
            value = item.get(field, 0)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{field} must be numeric")
            numbers[field] = max(0, int(value))
        extra = item.get("extra") or {}
        if not isinstance(extra, dict):
            raise ValueError("extra must be an object")
        return RawPost(
            id=item["id"],
            channel=item["channel"],
            source=text_fields["source"],
            title=text_fields["title"],
            body=text_fields["body"],
            url=text_fields["url"],
            author=text_fields["author"],
            score=numbers["score"],
            comments=numbers["comments"],
            created_at=text_fields["created_at"],
            extra=extra,
        )

    def latest_week_with_posts(self) -> str | None:
        raw_dir = self.root / "raw"
        if not raw_dir.exists():
            return None
        for week_dir in sorted((p for p in raw_dir.iterdir() if p.is_dir()), reverse=True):
            if self.read_week_posts(week_dir.name):
                return week_dir.name
        return None

    def write_prepared(
        self, week: str, bundle: AgentBundle, instructions: str
    ) -> dict[str, Path]:
        out = self.root / "prepared" / week
        bundle_path = self._atomic_write(
            out / "agent_bundle.json",
            json.dumps(bundle.to_dict(), indent=2, ensure_ascii=False) + "\n",
        )
        instructions_path = self._atomic_write(out / "AGENT_INSTRUCTIONS.md", instructions)
        return {"bundle": bundle_path, "instructions": instructions_path}

    def read_prepared(self, week: str) -> AgentBundle | None:
        from server.discovery.analyze.corpus import records_digest
        from server.discovery.analyze.models import AgentBundle, ContractError

        path = self.root / "prepared" / week / "agent_bundle.json"
        if not path.exists():
            return None
        try:
            bundle = AgentBundle.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ContractError) as exc:
            raise ValueError(f"invalid prepared bundle {path}: {exc}") from exc
        actual = records_digest(bundle.records)
        if actual != bundle.records_digest:
            raise ValueError(f"invalid prepared bundle {path}: records digest mismatch")
        return bundle

    def prepared_exists(self, week: str) -> bool:
        base = self.root / "prepared" / week
        return (base / "agent_bundle.json").is_file() and (base / "AGENT_INSTRUCTIONS.md").is_file()

    def write_analyzed(
        self, week: str, report: TopicReport, markdown: str
    ) -> dict[str, Path]:
        out = self.root / "analyzed" / week
        # Both payloads are fully materialized before either destination changes.
        json_content = json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"
        markdown_content = markdown if markdown.endswith("\n") else markdown + "\n"
        json_path = self._atomic_write(out / "topics.json", json_content)
        md_path = self._atomic_write(out / "topics.md", markdown_content)
        return {"json": json_path, "md": md_path}

    def read_analyzed(self, week: str) -> TopicReport | None:
        from server.discovery.analyze.models import ContractError, TopicReport

        path = self.root / "analyzed" / week / "topics.json"
        if not path.exists():
            return None
        try:
            return TopicReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, json.JSONDecodeError, ContractError) as exc:
            raise ValueError(f"invalid analyzed report {path}: {exc}") from exc

    def analyzed_exists(self, week: str) -> bool:
        base = self.root / "analyzed" / week
        return (base / "topics.json").is_file() and (base / "topics.md").is_file()
