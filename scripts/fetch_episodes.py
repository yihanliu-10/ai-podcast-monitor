#!/usr/bin/env python3
"""Fetch new podcast episodes from YouTube RSS feeds and Bilibili."""

import sys
import io
import json
import hashlib
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={}"
ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
MEDIA_NS = "http://search.yahoo.com/mrss/"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "channels.yaml"
BILIBILI_CONFIG_PATH = PROJECT_ROOT / "config" / "bilibili.yaml"
STATE_PATH = PROJECT_ROOT / "data" / "processed.json"


def load_channels(config_path: Path) -> list:
    import yaml
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("channels", [])


def load_bilibili_cookies() -> dict:
    import yaml
    if not BILIBILI_CONFIG_PATH.exists():
        return {}
    with open(BILIBILI_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("cookies", {})


def load_processed(state_path: Path) -> set:
    if not state_path.exists():
        return set()
    with open(state_path, "r") as f:
        data = json.load(f)
    return set(data.get("processed_ids", []))


# ── YouTube ──────────────────────────────────────────────────────────────────

def fetch_youtube_feed(channel_id: str) -> list:
    url = RSS_URL_TEMPLATE.format(channel_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml_data = resp.read()
    except Exception as e:
        print(f"WARNING: Failed to fetch YouTube feed for {channel_id}: {e}", file=sys.stderr)
        return []

    root = ET.fromstring(xml_data)
    channel_name = root.findtext(f"{{{ATOM_NS}}}title", default="Unknown")
    episodes = []

    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        video_id = entry.findtext(f"{{{YT_NS}}}videoId", default="")
        title = entry.findtext(f"{{{ATOM_NS}}}title", default="")
        published = entry.findtext(f"{{{ATOM_NS}}}published", default="")
        link_el = entry.find(f"{{{ATOM_NS}}}link[@rel='alternate']")
        link = link_el.get("href", "") if link_el is not None else ""

        media_group = entry.find(f"{{{MEDIA_NS}}}group")
        description = ""
        views = 0
        if media_group is not None:
            description = media_group.findtext(f"{{{MEDIA_NS}}}description", default="")
            community = media_group.find(f"{{{MEDIA_NS}}}community")
            if community is not None:
                stats = community.find(f"{{{MEDIA_NS}}}statistics")
                if stats is not None:
                    views = int(stats.get("views", "0"))

        episodes.append({
            "video_id": video_id,
            "title": title,
            "channel_name": channel_name,
            "channel_id": channel_id,
            "published": published,
            "url": link,
            "description": description[:500],
            "views": views,
            "platform": "youtube",
        })

    return episodes


# ── Bilibili ──────────────────────────────────────────────────────────────────

_WBI_MIXIN_KEY = None

BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com",
    "Origin": "https://www.bilibili.com",
}


def _init_bilibili_cookies(cookies: dict) -> None:
    """Fetch fresh buvid3/buvid4 from B站 fingerprint API to bypass anti-bot."""
    try:
        import requests
        spi = requests.get("https://api.bilibili.com/x/frontend/finger/spi",
                           headers=BILIBILI_HEADERS, timeout=10).json()
        if spi.get("code") == 0:
            cookies["buvid3"] = spi["data"]["b_3"]
            cookies["buvid4"] = spi["data"]["b_4"]
    except Exception as e:
        print(f"WARNING: buvid init failed: {e}", file=sys.stderr)


def _get_wbi_mixin_key(cookies: dict) -> str:
    global _WBI_MIXIN_KEY
    if _WBI_MIXIN_KEY:
        return _WBI_MIXIN_KEY
    import requests
    nav = requests.get("https://api.bilibili.com/x/web-interface/nav",
                       cookies=cookies, headers=BILIBILI_HEADERS, timeout=10).json()
    wbi = nav["data"]["wbi_img"]
    img_key = wbi["img_url"].split("/")[-1].split(".")[0]
    sub_key = wbi["sub_url"].split("/")[-1].split(".")[0]
    TAB = [46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,
           29,28,14,39,12,38,41,13,37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,
           22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52]
    mixed = img_key + sub_key
    _WBI_MIXIN_KEY = "".join(mixed[i] for i in TAB)[:32]
    return _WBI_MIXIN_KEY


def _wbi_sign(params: dict, cookies: dict) -> dict:
    """Add WBI signature to Bilibili API params."""
    try:
        mixin_key = _get_wbi_mixin_key(cookies)
        params["wts"] = str(int(time.time()))
        s = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}"
                     for k, v in sorted(params.items()))
        params["w_rid"] = hashlib.md5((s + mixin_key).encode()).hexdigest()
    except Exception as e:
        print(f"WARNING: WBI sign failed: {e}", file=sys.stderr)
    return params


def fetch_bilibili_feed(uid: str, channel_name: str, cookies: dict) -> list:
    import requests
    for attempt in range(3):
        try:
            if attempt > 0:
                time.sleep(2 * attempt)
                _init_bilibili_cookies(cookies)  # refresh buvid on retry
            params = _wbi_sign({"mid": uid, "ps": "20", "pn": "1", "order": "pubdate"},
                               cookies)
            resp = requests.get("https://api.bilibili.com/x/space/wbi/arc/search",
                                params=params, cookies=cookies, headers=BILIBILI_HEADERS, timeout=15)
            if resp.status_code == 412:
                print(f"WARNING: Bilibili 412 for uid={uid}, attempt {attempt+1}", file=sys.stderr)
                continue
            data = resp.json()
            if data.get("code") != 0:
                print(f"WARNING: Bilibili API error uid={uid}: {data.get('message','')}", file=sys.stderr)
                return []
            break
        except Exception as e:
            print(f"WARNING: Failed to fetch Bilibili feed for uid={uid}: {e}", file=sys.stderr)
            if attempt == 2:
                return []
            continue
    else:
        return []

    episodes = []
    vlist = data.get("data", {}).get("list", {}).get("vlist") or []
    for v in vlist:
        bvid = v.get("bvid", "")
        # B站 API uses 'created' field (unix timestamp)
        pub_ts = v.get("created") or v.get("pubdate", 0)
        pub_iso = datetime.fromtimestamp(pub_ts, tz=timezone.utc).isoformat()
        episodes.append({
            "video_id": bvid,
            "title": v.get("title", ""),
            "channel_name": channel_name or v.get("author", ""),
            "channel_id": uid,
            "published": pub_iso,
            "url": f"https://www.bilibili.com/video/{bvid}",
            "description": v.get("description", "")[:500],
            "views": v.get("play", 0),
            "platform": "bilibili",
        })

    return episodes


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Fetch new podcast episodes")
    parser.add_argument("--since", type=str, default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if args.since:
        cutoff = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    channels = load_channels(CONFIG_PATH)
    bilibili_cookies = load_bilibili_cookies()
    if any(ch.get("platform") == "bilibili" for ch in channels):
        _init_bilibili_cookies(bilibili_cookies)
    processed = set() if args.all else load_processed(STATE_PATH)

    print(f"Checking {len(channels)} channels (since {cutoff.strftime('%Y-%m-%d')})...",
          file=sys.stderr)

    all_new = []
    for ch in channels:
        platform = ch.get("platform", "youtube")
        if platform == "bilibili":
            episodes = fetch_bilibili_feed(ch["channel_id"], ch.get("name", ""), bilibili_cookies)
        else:
            episodes = fetch_youtube_feed(ch["channel_id"])

        for ep in episodes:
            if ep["video_id"] in processed:
                continue
            try:
                pub_date = datetime.fromisoformat(ep["published"])
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                if pub_date < cutoff:
                    continue
            except (ValueError, TypeError):
                pass

            ep["category"] = ch.get("category", "general")
            all_new.append(ep)

    all_new.sort(key=lambda x: x.get("published", ""), reverse=True)

    print(f"Found {len(all_new)} new episodes", file=sys.stderr)
    print(json.dumps(all_new, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
