#!/usr/bin/env python3
"""Resolve a YouTube channel name or @handle to its channel_id."""

import sys
import json
import re
import urllib.request
import urllib.parse
from typing import Optional


def resolve_handle(handle: str) -> Optional[dict]:
    """Fetch https://www.youtube.com/@handle and extract channel info."""
    if not handle.startswith("@"):
        handle = "@" + handle
    url = f"https://www.youtube.com/{urllib.parse.quote(handle)}"
    return _extract_from_url(url)


def resolve_by_search(query: str) -> Optional[dict]:
    """Search YouTube for the channel name and extract from results page."""
    search_url = (
        "https://www.youtube.com/results?"
        + urllib.parse.urlencode({"search_query": query, "sp": "EgIQAg=="})  # sp = Channels filter
    )
    return _extract_from_url(search_url)


def _extract_from_url(url: str) -> Optional[dict]:
    """Fetch a YouTube page and extract channel_id and channel name."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"ERROR: Failed to fetch {url}: {e}", file=sys.stderr)
        return None

    # Extract channel_id
    cid_match = re.search(r'"(?:channelId|externalId)"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', html)
    if not cid_match:
        return None

    channel_id = cid_match.group(1)

    # Extract channel name
    name = None
    name_match = re.search(r'"channelMetadataRenderer"[^}]*"title"\s*:\s*"([^"]+)"', html)
    if name_match:
        name = name_match.group(1)
    else:
        # Fallback: og:title
        og_match = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', html)
        if og_match:
            name = og_match.group(1)

    # Extract handle
    handle = None
    handle_match = re.search(r'"canonicalChannelUrl"\s*:\s*"https?://www\.youtube\.com/(@[^"]+)"', html)
    if handle_match:
        handle = handle_match.group(1)
    else:
        handle_match = re.search(r'"vanityChannelUrl"\s*:\s*"[^"]*(@[^"]+)"', html)
        if handle_match:
            handle = handle_match.group(1)

    return {
        "channel_id": channel_id,
        "name": name or "Unknown",
        "handle": handle,
    }


def resolve(query: str) -> Optional[dict]:
    """
    Resolve a channel query (name, @handle, or URL) to channel info.
    Returns {"channel_id": "UC...", "name": "...", "handle": "@..."} or None.
    """
    query = query.strip()

    # Already a channel_id
    if re.match(r"^UC[a-zA-Z0-9_-]{22}$", query):
        return {"channel_id": query, "name": None, "handle": None}

    # YouTube URL
    if "youtube.com/" in query:
        return _extract_from_url(query)

    # @handle
    if query.startswith("@"):
        result = resolve_handle(query)
        if result:
            return result

    # Try as @handle (remove spaces, lowercase)
    handle_guess = query.replace(" ", "").lower()
    result = resolve_handle(handle_guess)
    if result:
        return result

    # Fall back to search
    return resolve_by_search(query)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Resolve YouTube channel name/handle to channel_id")
    parser.add_argument("query", help="Channel name, @handle, or YouTube URL")
    args = parser.parse_args()

    result = resolve(args.query)
    if result is None:
        print(json.dumps({"error": f"Could not resolve channel: {args.query}"}))
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
