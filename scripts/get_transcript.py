#!/usr/bin/env python3
"""Download and chunk a video transcript (YouTube or Bilibili)."""

import sys
import io
import json
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

CHUNK_CHAR_LIMIT = 48_000
OVERLAP_CHARS = 1_000
TIMESTAMP_INTERVAL = 300

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BILIBILI_CONFIG_PATH = PROJECT_ROOT / "config" / "bilibili.yaml"


def format_timestamp(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


# ── YouTube ───────────────────────────────────────────────────────────────────

def fetch_youtube_transcript(video_id: str) -> dict:
    ytt = YouTubeTranscriptApi()
    try:
        transcript_list = ytt.list(video_id)
    except TranscriptsDisabled:
        return {"error": "transcripts_disabled", "snippets": None}
    except VideoUnavailable:
        return {"error": "video_unavailable", "snippets": None}
    except Exception as e:
        return {"error": f"list_failed: {str(e)}", "snippets": None}

    try:
        transcript = transcript_list.find_transcript(["en"])
        fetched = transcript.fetch()
        return {
            "snippets": [{"text": s.text, "start": s.start, "duration": s.duration}
                         for s in fetched],
            "language": transcript.language_code,
            "is_generated": transcript.is_generated,
            "is_translated": False,
            "error": None,
        }
    except NoTranscriptFound:
        pass

    for transcript in transcript_list:
        try:
            if transcript.is_translatable:
                translated = transcript.translate("en")
                fetched = translated.fetch()
                return {
                    "snippets": [{"text": s.text, "start": s.start, "duration": s.duration}
                                 for s in fetched],
                    "language": transcript.language_code,
                    "is_generated": transcript.is_generated,
                    "is_translated": True,
                    "error": None,
                }
            else:
                fetched = transcript.fetch()
                return {
                    "snippets": [{"text": s.text, "start": s.start, "duration": s.duration}
                                 for s in fetched],
                    "language": transcript.language_code,
                    "is_generated": transcript.is_generated,
                    "is_translated": False,
                    "error": f"non_english_untranslated:{transcript.language_code}",
                }
        except Exception:
            continue

    return {"error": "no_usable_transcript", "snippets": None}


# ── Bilibili ──────────────────────────────────────────────────────────────────

def load_bilibili_cookies() -> dict:
    import yaml
    if not BILIBILI_CONFIG_PATH.exists():
        return {}
    with open(BILIBILI_CONFIG_PATH, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("cookies", {})


def fetch_bilibili_transcript(bvid: str) -> dict:
    import requests
    cookies = load_bilibili_cookies()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36", "Referer": "https://www.bilibili.com"}

    # Step 1: get CID
    try:
        resp = requests.get(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}",
                            cookies=cookies, headers=headers, timeout=10)
        pages = resp.json()
        if pages.get("code") != 0 or not pages.get("data"):
            return {"error": f"bilibili_cid_failed: {pages.get('message','')}", "snippets": None}
        cid = pages["data"][0]["cid"]
    except Exception as e:
        return {"error": f"bilibili_cid_error: {e}", "snippets": None}

    # Step 2: get subtitle list
    try:
        resp = requests.get(
            f"https://api.bilibili.com/x/player/v2?cid={cid}&bvid={bvid}",
            cookies=cookies, headers=headers, timeout=10)
        player_data = resp.json()
        subtitles = (player_data.get("data", {})
                                .get("subtitle", {})
                                .get("subtitles", []))
    except Exception as e:
        return {"error": f"bilibili_subtitle_list_error: {e}", "snippets": None}

    if not subtitles:
        return {"error": "no_usable_transcript", "snippets": None}

    # Prefer Chinese subtitle, fallback to first available
    subtitle_url = None
    language = "unknown"
    for sub in subtitles:
        lang = sub.get("lan", "")
        if "zh" in lang:
            subtitle_url = sub.get("subtitle_url", "")
            language = lang
            break
    if not subtitle_url:
        subtitle_url = subtitles[0].get("subtitle_url", "")
        language = subtitles[0].get("lan", "unknown")

    if subtitle_url.startswith("//"):
        subtitle_url = "https:" + subtitle_url

    # Step 3: download subtitle JSON
    try:
        resp = requests.get(subtitle_url, headers=headers, timeout=15)
        sub_data = resp.json()
        body = sub_data.get("body", [])
    except Exception as e:
        return {"error": f"bilibili_subtitle_download_error: {e}", "snippets": None}

    if not body:
        return {"error": "no_usable_transcript", "snippets": None}

    snippets = []
    for item in body:
        start = item.get("from", 0)
        end = item.get("to", start)
        snippets.append({
            "text": item.get("content", ""),
            "start": start,
            "duration": end - start,
        })

    return {
        "snippets": snippets,
        "language": language,
        "is_generated": True,
        "is_translated": False,
        "error": None,
    }


# ── Chunking ──────────────────────────────────────────────────────────────────

def chunk_transcript(snippets: list) -> list:
    if not snippets:
        return []

    chunks = []
    current_text = ""
    current_start = snippets[0]["start"]
    last_timestamp_at = 0

    for s in snippets:
        if s["start"] - last_timestamp_at >= TIMESTAMP_INTERVAL:
            marker = f"\n[{format_timestamp(s['start'])}]\n"
            current_text += marker
            last_timestamp_at = s["start"]

        current_text += s["text"].strip() + " "

        if len(current_text) >= CHUNK_CHAR_LIMIT:
            chunks.append({
                "chunk_index": len(chunks),
                "start_time": format_timestamp(current_start),
                "end_time": format_timestamp(s["start"] + s.get("duration", 0)),
                "text": current_text.strip(),
                "char_count": len(current_text.strip()),
            })
            current_text = current_text[-OVERLAP_CHARS:]
            current_start = s["start"]

    if current_text.strip():
        last_snippet = snippets[-1]
        chunks.append({
            "chunk_index": len(chunks),
            "start_time": format_timestamp(current_start),
            "end_time": format_timestamp(
                last_snippet["start"] + last_snippet.get("duration", 0)
            ),
            "text": current_text.strip(),
            "char_count": len(current_text.strip()),
        })

    return chunks


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Get video transcript (YouTube or Bilibili)")
    parser.add_argument("video_id", help="YouTube video ID or Bilibili BV号")
    args = parser.parse_args()

    video_id = args.video_id
    is_bilibili = video_id.startswith("BV") or video_id.startswith("bv")

    if is_bilibili:
        result = fetch_bilibili_transcript(video_id)
    else:
        result = fetch_youtube_transcript(video_id)

    if result.get("error") and result.get("snippets") is None:
        output = {
            "video_id": video_id,
            "error": result["error"],
            "chunks": [],
            "total_duration_seconds": 0,
            "total_duration_formatted": "00:00:00",
            "num_chunks": 0,
        }
    else:
        snippets = result["snippets"]
        chunks = chunk_transcript(snippets)
        total_duration = 0
        if snippets:
            last = snippets[-1]
            total_duration = last["start"] + last.get("duration", 0)

        output = {
            "video_id": video_id,
            "error": result.get("error"),
            "language": result.get("language", "unknown"),
            "is_generated": result.get("is_generated", False),
            "is_translated": result.get("is_translated", False),
            "total_duration_seconds": total_duration,
            "total_duration_formatted": format_timestamp(total_duration),
            "total_chars": sum(c["char_count"] for c in chunks),
            "num_chunks": len(chunks),
            "chunks": chunks,
        }

    json.dump(output, sys.stdout, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
