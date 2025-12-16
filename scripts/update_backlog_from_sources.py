#!/usr/bin/env python3
"""
Update data/backlog/<series>.yaml automatically from chapter sources.

Currently supports RSS sources configured in data/series.yaml as `rss: "<url>"`.

Behavior:
  - Detect latest chapter number from RSS entry titles.
  - Detect latest existing chapter number from already generated posts (spoiler variant by default).
  - Append missing chapters to backlog entries so daily runs can catch up.

Cost:
  - No OpenAI usage. Only RSS fetch + local file updates.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import feedparser
import frontmatter
import yaml


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONTENT_DIR = ROOT_DIR / "content" / "posts"
SERIES_FILE = DATA_DIR / "series.yaml"
BACKLOG_DIR = DATA_DIR / "backlog"


DEFAULT_FORCE_MODES = ["spoiler"]
BACKLOG_FILL_LIMIT = int(os.getenv("BACKLOG_FILL_LIMIT", "50"))
VARIANT_FOR_PROGRESS = os.getenv("BACKLOG_PROGRESS_VARIANT", "spoiler").strip() or "spoiler"

UTC = timezone.utc
SYNTHETIC_BASE = datetime(2020, 1, 1, tzinfo=UTC)


def extract_chapter_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value)
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None


def load_series() -> List[Dict[str, Any]]:
    text = SERIES_FILE.read_text(encoding="utf-8-sig")
    return yaml.safe_load(text) or []


def get_existing_max_chapter(series_slug: str, variant: str) -> int:
    series_root = CONTENT_DIR / series_slug
    if not series_root.exists():
        return 0
    max_ch = 0
    for path in series_root.rglob("*.md"):
        if "glossary" in path.parts:
            continue
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.get("article_variant") != variant:
            continue
        ch = extract_chapter_number(post.get("chapter"))
        if ch and ch > max_ch:
            max_ch = ch
    return max_ch


def detect_latest_from_rss(rss_url: str) -> Optional[int]:
    feed = feedparser.parse(rss_url)
    nums: List[int] = []
    for entry in getattr(feed, "entries", [])[:200]:
        title = getattr(entry, "title", "") or ""
        n = extract_chapter_number(title)
        if n is not None:
            nums.append(n)
    return max(nums) if nums else None


def load_backlog_entries(series_slug: str) -> List[Dict[str, Any]]:
    path = BACKLOG_DIR / f"{series_slug}.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("entries") or data.get("topics") or []


def save_backlog_entries(series_slug: str, entries: List[Dict[str, Any]]) -> bool:
    BACKLOG_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKLOG_DIR / f"{series_slug}.yaml"
    new_data = {"entries": entries}
    new_text = yaml.safe_dump(new_data, allow_unicode=True, sort_keys=False)
    old_text = path.read_text(encoding="utf-8") if path.exists() else ""
    if old_text == new_text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def ensure_backlog_range(
    series_slug: str,
    series_name: str,
    start_ch: int,
    latest_ch: int,
    force_modes: Optional[List[str]] = None,
) -> Tuple[int, bool]:
    if start_ch <= 0 or latest_ch <= 0 or start_ch > latest_ch:
        return 0, False

    existing = load_backlog_entries(series_slug)
    existing_numbers = {
        extract_chapter_number(item.get("chapter_number") or item.get("chapter") or item.get("title"))
        for item in existing
    }

    added = 0
    updated = False
    modes = force_modes or DEFAULT_FORCE_MODES
    for ch in range(start_ch, latest_ch + 1):
        if BACKLOG_FILL_LIMIT and added >= BACKLOG_FILL_LIMIT:
            break
        if ch in existing_numbers:
            continue

        entry = {
            "title": f"{series_name} 第{ch}話",
            "chapter": f"第{ch}話",
            "chapter_number": ch,
            "date": (SYNTHETIC_BASE + timedelta(days=ch)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "force_modes": list(modes),
        }
        existing.append(entry)
        existing_numbers.add(ch)
        added += 1
        updated = True

    # Keep stable order: by (date, chapter_number)
    existing.sort(key=lambda x: (str(x.get("date") or ""), int(x.get("chapter_number") or 0)))

    if updated:
        wrote = save_backlog_entries(series_slug, existing)
        return added, wrote
    return 0, False


def main() -> int:
    series_list = load_series()
    changed_any = False
    for series in series_list:
        if series.get("manual", False):
            continue
        slug = series.get("slug")
        name = series.get("name", slug)
        rss = (series.get("rss") or "").strip()
        if not slug:
            continue
        if not rss:
            print(f"[INFO] {name}: rss未設定のためスキップ")
            continue

        latest = detect_latest_from_rss(rss)
        if not latest:
            print(f"[WARN] {name}: RSSから話数を抽出できませんでした（タイトルに数字が無い可能性）")
            continue

        existing_max = get_existing_max_chapter(slug, VARIANT_FOR_PROGRESS)
        start = existing_max + 1
        added, wrote = ensure_backlog_range(slug, name, start, latest, force_modes=DEFAULT_FORCE_MODES)
        if wrote:
            changed_any = True
        print(f"[OK] {name}: latest={latest}, existing_max={existing_max}, added={added}")

    if not changed_any:
        print("[INFO] backlog更新なし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

