#!/usr/bin/env python3
"""
Fix known-bad internal links in Markdown content.

Targets:
- Old permalink shape that incorrectly includes series slug:
    /posts/<series_slug>/YYYY/MM/<slug>/  ->  /posts/YYYY/MM/<slug>/
  (also handles absolute URLs under the site baseURL)

- Old "series list" links that incorrectly used Japanese series name under /posts/:
    /posts/<series_name>/  ->  /series/<series_slug>/
  (also handles absolute URLs under the site baseURL)

Usage:
  python scripts/fix_internal_links.py
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent
CONTENT_POSTS = ROOT / "content" / "posts"
SERIES_YAML = ROOT / "data" / "series.yaml"

SITE_BASEURL = "https://pontarou0610.github.io/manga-kousatsu-hub"


def load_series_map() -> tuple[dict[str, str], set[str]]:
    data = yaml.safe_load(SERIES_YAML.read_text(encoding="utf-8")) or []
    name_to_slug: dict[str, str] = {}
    slugs: set[str] = set()
    for item in data:
        name = (item.get("name") or "").strip()
        slug = (item.get("slug") or "").strip()
        if not name or not slug:
            continue
        name_to_slug[name] = slug
        slugs.add(slug)
    return name_to_slug, slugs


def fix_text(text: str, *, name_to_slug: dict[str, str], slugs: set[str]) -> str:
    # Fix old permalink structure that incorrectly included series slug.
    def repl_old(m: re.Match[str]) -> str:
        prefix, series_slug, rest = m.group(1), m.group(2), m.group(3)
        if series_slug not in slugs:
            return m.group(0)
        return f"{prefix}{rest}"

    # Relative and absolute forms.
    text = re.sub(r"(/posts/)([a-z0-9-]+)/(\d{4}/\d{2}/[^)\s\"']+)", repl_old, text)
    text = re.sub(
        rf"({re.escape(SITE_BASEURL)}/posts/)([a-z0-9-]+)/(\d{{4}}/\d{{2}}/[^)\s\"']+)",
        repl_old,
        text,
    )

    # Fix old series-list links like /posts/アオアシ/ -> /series/aoashi/
    for name, slug in name_to_slug.items():
        text = text.replace(f"/posts/{name}/", f"/series/{slug}/")
        text = text.replace(f"{SITE_BASEURL}/posts/{name}/", f"{SITE_BASEURL}/series/{slug}/")

    # If taxonomy pages are disabled, redirect legacy series-tag links to the series page.
    for slug in slugs:
        text = text.replace(f"/tags/{slug}/", f"/series/{slug}/")
        text = text.replace(f"{SITE_BASEURL}/tags/{slug}/", f"{SITE_BASEURL}/series/{slug}/")

    return text


def main() -> int:
    if not SERIES_YAML.exists():
        raise SystemExit(f"[ERROR] missing {SERIES_YAML}")
    if not CONTENT_POSTS.exists():
        raise SystemExit(f"[ERROR] missing {CONTENT_POSTS}")

    name_to_slug, slugs = load_series_map()
    md_files = sorted(CONTENT_POSTS.rglob("*.md"))

    changed = 0
    for path in md_files:
        original = path.read_text(encoding="utf-8")
        updated = fix_text(original, name_to_slug=name_to_slug, slugs=slugs)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print(f"[OK] {path.relative_to(ROOT)}")

    print(f"\nDone. Updated {changed} file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
