#!/usr/bin/env python3
"""Manage podcast channels: add, list, remove."""

import sys
import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "channels.yaml"

# Import resolve from sibling module
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from resolve_channel import resolve


def load_config():
    if not CONFIG_PATH.exists():
        return {"channels": []}
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {"channels": []}


def save_config(config):
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def cmd_list(args):
    config = load_config()
    channels = config.get("channels", [])
    print(json.dumps(channels, ensure_ascii=False, indent=2))
    print(f"{len(channels)} channel(s) configured", file=sys.stderr)


def cmd_add(args):
    query = args.query
    category = args.category

    print(f"Resolving \"{query}\"...", file=sys.stderr)
    result = resolve(query)
    if result is None:
        print(f"ERROR: Could not resolve \"{query}\". Try a @handle or YouTube URL.", file=sys.stderr)
        sys.exit(1)

    channel_id = result["channel_id"]
    name = result.get("name") or query
    handle = result.get("handle")

    # Check for duplicates
    config = load_config()
    for ch in config.get("channels", []):
        if ch["channel_id"] == channel_id:
            print(f"Already exists: {ch['name']} ({channel_id})", file=sys.stderr)
            sys.exit(0)

    entry = {"name": name, "channel_id": channel_id, "category": category}
    if handle:
        entry["handle"] = handle

    config.setdefault("channels", []).append(entry)
    save_config(config)

    print(json.dumps(entry, ensure_ascii=False, indent=2))
    print(f"Added \"{name}\" ({category})", file=sys.stderr)


def cmd_sync(args):
    txt_path = PROJECT_ROOT / "config" / "channels.txt"
    if not txt_path.exists():
        print(json.dumps({"error": "config/channels.txt not found"}))
        sys.exit(1)

    # Parse txt: ignore empty lines and comments
    with open(txt_path, "r") as f:
        txt_entries = []
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                txt_entries.append(line)

    config = load_config()
    existing = config.get("channels", [])

    # Build lookup: lowercase name/handle -> channel entry
    existing_by_key = {}
    for ch in existing:
        existing_by_key[ch["name"].lower()] = ch
        if ch.get("handle"):
            existing_by_key[ch["handle"].lower()] = ch

    added = []
    kept = []
    matched_ids = set()

    for entry in txt_entries:
        key = entry.lower()
        if key in existing_by_key:
            ch = existing_by_key[key]
            kept.append(ch)
            matched_ids.add(ch["channel_id"])
        else:
            # New channel - resolve it
            print(f"Resolving \"{entry}\"...", file=sys.stderr)
            result = resolve(entry)
            if result is None:
                print(f"WARNING: Could not resolve \"{entry}\", skipping.", file=sys.stderr)
                continue
            # Check if resolved channel_id already matched (duplicate entry with different casing)
            if result["channel_id"] in matched_ids:
                continue
            new_ch = {
                "name": result.get("name") or entry,
                "channel_id": result["channel_id"],
                "category": "general",
            }
            if result.get("handle"):
                new_ch["handle"] = result["handle"]
            added.append(new_ch)
            matched_ids.add(result["channel_id"])

    # Removed = existing channels whose channel_id wasn't matched
    removed = [ch for ch in existing if ch["channel_id"] not in matched_ids]

    # Build new channel list preserving order from txt
    new_channels = kept + added
    config["channels"] = new_channels
    save_config(config)

    result = {"added": added, "removed": removed, "kept": len(kept), "total": len(new_channels)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Sync done: +{len(added)} added, -{len(removed)} removed, {len(kept)} kept", file=sys.stderr)


def cmd_remove(args):
    name_query = args.name.lower()
    config = load_config()
    channels = config.get("channels", [])
    original_len = len(channels)

    config["channels"] = [
        ch for ch in channels
        if name_query not in ch.get("name", "").lower()
    ]

    removed_channels = [
        ch for ch in channels
        if name_query in ch.get("name", "").lower()
    ]
    if not removed_channels:
        print(json.dumps({"error": f"No channel matching \"{args.name}\" found."}))
        sys.exit(1)

    save_config(config)
    print(json.dumps(removed_channels, ensure_ascii=False, indent=2))
    print(f"Removed {len(removed_channels)} channel(s) matching \"{args.name}\".", file=sys.stderr)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Manage podcast channels")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List all channels")

    p_add = sub.add_parser("add", help="Add a channel by name, @handle, or URL")
    p_add.add_argument("query", help="Channel name, @handle, or YouTube URL")
    p_add.add_argument("--category", default="general", help="Category tag (default: general)")

    p_rm = sub.add_parser("remove", help="Remove a channel by name")
    p_rm.add_argument("name", help="Channel name (partial match)")

    sub.add_parser("sync", help="Sync channels from config/channels.txt to YAML")

    args = parser.parse_args()
    {"list": cmd_list, "add": cmd_add, "remove": cmd_remove, "sync": cmd_sync}[args.command](args)


if __name__ == "__main__":
    main()
