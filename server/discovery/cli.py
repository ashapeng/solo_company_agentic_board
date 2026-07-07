from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from server.discovery.channels import build_channel
from server.discovery.doctor import run_doctor
from server.discovery.store import DiscoveryStore, iso_week
from server.discovery.watchlist import load_watchlist

DEFAULT_DATA_DIR = Path("data/discovery")


def _cmd_fetch(args: argparse.Namespace) -> int:
    week = args.week or iso_week()
    watchlist = load_watchlist(Path(args.watchlist) if args.watchlist else None)
    store = DiscoveryStore(Path(args.data_dir))
    runs = []
    for channel_name, items in watchlist.items():
        if not items:
            continue
        channel = build_channel(channel_name)
        for item in items:
            label = item["label"]
            entry = {"channel": channel_name, "label": label, "fetched": 0, "new": 0, "file": None, "error": None}
            try:
                posts = channel.fetch(item)
                new_posts = store.filter_new(posts)
                path = store.write_raw(week, channel_name, label, new_posts)
                store.mark_seen(new_posts)
                entry.update(fetched=len(posts), new=len(new_posts), file=path.name)
            except Exception as exc:
                entry["error"] = str(exc)
            runs.append(entry)
            print(f"{channel_name}/{label}: fetched={entry['fetched']} new={entry['new']}"
                  + (f" ERROR: {entry['error']}" if entry["error"] else ""))
    manifest = {
        "week": week,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "runs": runs,
        "doctor": [asdict(h) for h in run_doctor(sorted({r["channel"] for r in runs}))],
    }
    store.write_manifest(week, manifest)
    print(f"manifest: {store.root / 'raw' / week / 'manifest.json'}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    names = args.channels.split(",") if args.channels else None
    for h in run_doctor(names):
        print(f"{h.channel:12} {h.status:12} {h.detail}")
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    latest = DiscoveryStore(Path(args.data_dir)).latest_manifest()
    if latest is None:
        print("no fetch runs recorded yet")
        return 0
    week, manifest = latest
    total_new = sum(r["new"] for r in manifest["runs"])
    errors = [r for r in manifest["runs"] if r["error"]]
    print(f"latest run: {week} ({manifest['generated_at']})")
    print(f"items: {len(manifest['runs'])}, new posts: {total_new}, errors: {len(errors)}")
    for r in errors:
        print(f"  ERROR {r['channel']}/{r['label']}: {r['error']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch all watchlist items for the week")
    fetch.add_argument("--watchlist", default=None)
    fetch.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    fetch.add_argument("--week", default=None)
    fetch.set_defaults(func=_cmd_fetch)

    doctor = sub.add_parser("doctor", help="probe channel health")
    doctor.add_argument("--channels", default=None)
    doctor.set_defaults(func=_cmd_doctor)

    status = sub.add_parser("status", help="summarize the latest fetch run")
    status.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    status.set_defaults(func=_cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)
