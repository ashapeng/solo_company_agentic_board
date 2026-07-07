from __future__ import annotations

from pathlib import Path

import yaml

from server.discovery.channels.base import slugify

DEFAULT_PATH = Path(__file__).parent / "watchlist.yaml"

_REQUIRED_FIELD = {
    "reddit": "sub",
    "hackernews": "query",
    "youtube": "query",
    "github": "query",
    "producthunt": "topic",
    "rss": "url",
    "sam_gov": "keywords",
    "grants_gov": "keywords",
    "canadabuys": "keywords",
    "agent_reach": "channel",
    "fake": "query",
}
GOV_CHANNELS = ("sam_gov", "grants_gov", "canadabuys")
KNOWN_SECTIONS = set(_REQUIRED_FIELD) - set(GOV_CHANNELS) | {"gov"}

_DEFAULTS = {"reddit": {"sort": "top", "window": "week"}}


class WatchlistError(ValueError):
    pass


def load_watchlist(path: Path | None = None) -> dict[str, list[dict]]:
    raw = yaml.safe_load((path or DEFAULT_PATH).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise WatchlistError("watchlist root must be a mapping")

    flat: dict[str, list] = {}
    for section, items in raw.items():
        if section == "gov":
            for gov_name, gov_items in (items or {}).items():
                if gov_name not in GOV_CHANNELS:
                    raise WatchlistError(f"unknown gov channel: {gov_name}")
                flat[gov_name] = gov_items or []
        elif section in KNOWN_SECTIONS:
            flat[section] = items or []
        else:
            raise WatchlistError(f"unknown channel section: {section}")

    result: dict[str, list[dict]] = {}
    for channel, items in flat.items():
        normalized = []
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise WatchlistError(f"{channel}[{i}] must be a mapping")
            required = _REQUIRED_FIELD[channel]
            if required not in item:
                raise WatchlistError(f"{channel}[{i}] missing required field: {required}")
            merged = {**_DEFAULTS.get(channel, {}), **item}
            if "label" not in merged:
                value = merged[required]
                merged["label"] = slugify(value[0] if isinstance(value, list) else str(value))
            normalized.append(merged)
        result[channel] = normalized
    return result
