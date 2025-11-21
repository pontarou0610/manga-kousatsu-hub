from __future__ import annotations

import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]


def slugify(value: str) -> str:
    """Lightweight slugify to avoid extra dependencies."""
    import re

    value = value.strip().lower()
    value = re.sub(r"[^\w\-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value or "post"


def build_front_matter(
    title: str,
    slug: str,
    date: dt.datetime,
    series: str,
    tags: List[str],
    author: str,
    chapter: str,
    description: str,
    draft: bool,
) -> str:
    tags_yaml = "\n".join([f'  - "{tag.strip()}"' for tag in tags if tag.strip()]) or '  - ""'
    return (
        "---\n"
        f'title: "{title}"\n'
        f'slug: "{slug}"\n'
        f"date: {date.isoformat()}\n"
        f'series: "{series}"\n'
        f"tags:\n{tags_yaml}\n"
        f'author: "{author}"\n'
        f'chapter: "{chapter}"\n'
        f'description: "{description}"\n'
        "images: []\n"
        f"draft: {str(draft).lower()}\n"
        "---\n\n"
    )


def build_default_body(title: str, series: str, chapter: str) -> str:
    """Provide a starter body so the post is never empty."""
    chapter_label = f"（{chapter}）" if chapter else ""
    return f"""## この記事のポイント
- {series}{chapter_label}の要点を3行でまとめます
- 読後すぐに役立つ気付きや学びを整理
- ネタバレは以降のセクションで明示して折りたたみます

## ネタバレなし概要
ここに概要を2〜3段落で書いてください。初見読者でも理解できるよう、背景と今回の注目点を簡潔に。

## 印象に残ったシーン
- 箇条書きで3〜5点
- 気付きや感情を短くメモ

## 考察・学び
1. 見出しを付けて深掘り（400〜600字）
2. もう1つ別軸で深掘り（300〜400字）

## ネタバレ詳細（折りたたみ推奨）
<details>
<summary>※ ネタバレを表示する</summary>

### 詳細な流れ
- ここに時系列でポイントを整理

### キャラクターの動機・伏線
- 伏線やセリフの意図を箇条書きで

</details>

## まとめ
- 今日の気付き/学びを3点
- 次回への予想や楽しみを書いて締める
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a new Hugo post with required SEO fields filled in automatically.",
    )
    parser.add_argument("--series", required=True, help="Series name (required)")
    parser.add_argument("--title", required=True, help="Post title")
    parser.add_argument("--slug", required=True, help="URL slug (no spaces)")
    parser.add_argument("--tags", required=True, help="Comma-separated tags (required)")
    parser.add_argument("--author", default="", help="Author name (optional)")
    parser.add_argument("--chapter", default="", help="Chapter memo (optional)")
    parser.add_argument("--description", default="", help="Meta description (optional)")
    parser.add_argument("--date", default=None, help="ISO date (default: now UTC)")
    parser.add_argument("--draft", action="store_true", help="Mark as draft")
    parser.add_argument("--publish", dest="draft", action="store_false", help="Mark as published")
    parser.set_defaults(draft=True)

    args = parser.parse_args()

    published_at = (
        dt.datetime.fromisoformat(args.date) if args.date else dt.datetime.now(dt.timezone.utc)
    )
    series_slug = slugify(args.series)
    month = f"{published_at:%m}"
    year = f"{published_at:%Y}"

    target_rel = Path("posts") / series_slug / year / month / f"{args.slug}.md"
    target_abs = ROOT / "content" / target_rel

    cmd = ["hugo", "new", str(target_rel)]
    print(f"[new_post] Running: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"[new_post] Failed to run hugo new: {exc}")
        return 1

    fm = build_front_matter(
        title=args.title,
        slug=args.slug,
        date=published_at,
        series=args.series,
        tags=[t.strip() for t in args.tags.split(",")],
        author=args.author,
        chapter=args.chapter,
        description=args.description,
        draft=args.draft,
    )

    try:
        original = target_abs.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"[new_post] Expected file not found: {target_abs}")
        return 1

    # Preserve existing body if any (should be empty right after hugo new).
    if original.startswith("---"):
        parts = original.split("---", 2)
        body = parts[2].lstrip("\n") if len(parts) == 3 else ""
    else:
        body = original
    if not body.strip():
        body = build_default_body(args.title, args.series, args.chapter)

    target_abs.write_text(fm + body, encoding="utf-8")
    print(f"[new_post] Created and filled front matter at {target_rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
