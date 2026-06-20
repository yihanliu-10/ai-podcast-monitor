#!/usr/bin/env python3
"""保存单集分析结果到本地 data/results/<video_id>.json，供网页读取与历史归档。

分析正文（markdown：概述/关键洞察/金句/建议）通过标准输入传入，
元数据通过命令行参数传入。
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

RESULTS_DIR = Path("data/results")


def main():
    parser = argparse.ArgumentParser(description="保存单集分析结果到本地 JSON")
    parser.add_argument("--video-id", required=True)
    parser.add_argument("--title", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--published", default="")
    parser.add_argument("--duration", default="")
    parser.add_argument("--category", default="general")
    parser.add_argument("--rating", default="")
    args = parser.parse_args()

    body = sys.stdin.read().strip()

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    record = {
        "video_id": args.video_id,
        "title": args.title,
        "channel": args.channel,
        "url": args.url,
        "published_date": args.published,
        "duration": args.duration,
        "category": args.category,
        "rating": args.rating,
        "analysis_date": datetime.date.today().isoformat(),
        "analysis_markdown": body,
    }

    out_path = RESULTS_DIR / f"{args.video_id}.json"
    out_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"saved": str(out_path), "video_id": args.video_id},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
