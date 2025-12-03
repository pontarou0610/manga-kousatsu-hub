from __future__ import annotations

import datetime as dt
import re
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

import frontmatter

from utils import (
    CONTENT_DIR,
    OGP_DIR,
    build_glossary_context,
    build_insight_context,
    build_spoiler_context,
    collect_existing_hashes,
    create_ogp_image,
    ensure_directory,
    generate_article_sections,
    hash_entry,
    load_entries_for_series,
    fetch_pexels_image,
    load_glossary_terms,
    select_glossary_terms,
    ensure_glossary_terms,
    load_series_config,
    load_state,
    render_markdown,
    save_state,
    slugify,
    write_markdown_file,
    select_backlog_entry,
    build_suggest_entry,
)


def log(message: str) -> None:
    print(f"[generate_posts] {message}")


def target_markdown_path(series_slug: str, published_at: dt.datetime, slug: str) -> Path:
    subdir = CONTENT_DIR / "posts" / series_slug / published_at.strftime("%Y/%m")
    return subdir / f"{slug}.md"


def fallback_path(series_slug: str, slug: str) -> Path:
    return CONTENT_DIR / "drafts" / series_slug / f"{slug}.md"


def _next_chapter_number(series_slug: str) -> int:
    """Find the next numeric chapter based on existing posts in the series."""
    base_dir = CONTENT_DIR / "posts" / series_slug
    max_num = 0
    if base_dir.exists():
        for md_file in base_dir.rglob("*.md"):
            try:
                post = frontmatter.load(md_file)
            except Exception:
                continue
            chapter_str = str(post.metadata.get("chapter", ""))
            match = re.search(r"\d+", chapter_str)
            if match:
                try:
                    num = int(match.group())
                    max_num = max(max_num, num)
                except ValueError:
                    continue
    return max_num + 1 if max_num else 1


def normalize_chapter_label(series: Dict[str, Any], entry: Dict[str, Any], published: dt.datetime) -> str:
    """Ensure chapter label is numeric style like '第100話' instead of '最新話'."""
    raw = (entry.get("chapter") or entry.get("title") or "").strip()
    match = re.search(r"\d+", raw)
    if match:
        return f"第{match.group()}話"
    # 数字が無い場合は既存記事の最大話数に続く番号を振る
    next_num = _next_chapter_number(series["slug"])
    return f"第{next_num}話"


def chapter_article_exists(series_slug: str, chapter: str, mode: str) -> bool:
    """Check if the same chapter and variant already exists for the series."""
    if not chapter:
        return False
    base_dir = CONTENT_DIR / "posts" / series_slug
    if not base_dir.exists():
        return False
    for md_file in base_dir.rglob("*.md"):
        try:
            post = frontmatter.load(md_file)
        except Exception:
            continue
        meta = post.metadata or {}
        if meta.get("chapter") == chapter and meta.get("article_variant") == mode:
            return True
    return False


def try_generate_article(
    series: Dict[str, Any],
    entry: Dict[str, Any],
    mode: str,
) -> Optional[Dict[str, Any]]:
    """Call OpenAI helper to generate article sections for a given entry."""
    try:
        return generate_article_sections(series, entry, mode)
    except Exception as exc:  # noqa: BLE001
        log(f"Failed to generate article sections via OpenAI ({mode}): {exc}")
        traceback.print_exc()
        return None


def build_auto_chapter_entry(series: Dict[str, Any], chapter_num: int) -> Dict[str, Any]:
    """Create a minimal auto-generated backlog entry starting from chapter 1."""
    now = dt.datetime.now(dt.timezone.utc)
    chapter_label = f"第{chapter_num}話"
    official_links = series.get("official_links", [])
    default_link = official_links[0].get("url") if official_links and official_links[0].get("url") else ""
    title = f"{series['name']} {chapter_label} ネタバレ・考察"
    summary = f"{series['name']}の{chapter_label}を時系列でまとめ、重要なセリフや伏線を整理します。"
    intro = f"{series['name']}の{chapter_label}をネタバレありで振り返り、考察と伏線整理を行います。"
    return {
        "id": f"{series['slug']}-auto-{chapter_num}",
        "title": title,
        "chapter": chapter_label,
        "date": now.isoformat(),
        "summary": summary,
        "intro": intro,
        "link": default_link,
        "research_links": [{"label": link.get("label", "公式リンク"), "url": link.get("url", "")} for link in official_links if link.get("url")],
        "is_backlog": True,
    }


def process_series(
    series: Dict[str, Any],
    processed_hashes: set[str],
    state: Dict[str, Any],
    limit: int,
) -> List[str]:
    """Generate up to `limit` articles per series (per run), plus glossary."""
    new_entries: List[str] = []

    # Always pull backlog entries (chapter 1 onward) up to the limit
    entries: List[Dict[str, Any]] = []
    while len(entries) < limit:
        entry = select_backlog_entry(series, state)
        if not entry:
            break
        entries.append(entry)

    # If backlog is empty, auto-generate sequential chapters starting from the next number.
    if len(entries) < limit:
        next_num = _next_chapter_number(series["slug"])
        while len(entries) < limit:
            auto_entry = build_auto_chapter_entry(series, next_num)
            entries.append(auto_entry)
            next_num += 1

    # 強制的にネタバレ記事のみを生成
    content_modes = ["spoiler", "insight"]
    entry_modes = ["spoiler", "insight"]

    def process_entry(entry: Dict[str, Any]) -> None:
        if not entry:
            return

        base_id = entry.get("id", entry.get("title", ""))
        is_suggest = bool(entry.get("is_suggest"))
        is_backlog = bool(entry.get("is_backlog"))
        is_fallback = bool(entry.get("is_fallback"))
        try:
            published = dt.datetime.fromisoformat(entry["date"])
        except Exception:  # noqa: BLE001
            published = dt.datetime.now(dt.timezone.utc)

        # normalize chapter to numeric style
        entry["chapter"] = normalize_chapter_label(series, entry, published)
        chapter_label = entry["chapter"]

        title_for_slug = entry.get("title", f"{series['slug']}-{published:%Y%m%d}")
        # スラッグ衝突を避けるため、バックログ/サジェスト/フォールバックは日付を付与
        if is_suggest or is_backlog or is_fallback:
            title_for_slug = f"{title_for_slug}-{published:%Y%m%d}"
        base_slug = slugify(title_for_slug)

        ogp_filename = f"{published:%Y%m%d}_{base_slug}.png"
        ogp_output = OGP_DIR / published.strftime("%Y") / ogp_filename
        try:
            ogp_image = create_ogp_image(
                entry.get("title", series["name"]),
                series["name"],
                entry.get("chapter", ""),
                ogp_output,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"OGP生成に失敗: {exc}")
            ogp_image = None

        draft_flag = bool(series.get("manual")) or not series.get("auto_publish", True)

        hero_image = fetch_pexels_image(entry.get("title", series["name"]))
        target_modes = entry.get("force_modes") or entry_modes

        for mode in target_modes:
            unique = hash_entry(series["slug"], base_id, mode)
            if unique in processed_hashes:
                continue

            if chapter_article_exists(series["slug"], chapter_label, mode):
                log(f"同じ話数の記事が既に存在するためスキップ: series={series['slug']} chapter={chapter_label} mode={mode}")
                continue

            sections = try_generate_article(series, entry, mode)
            if mode == "insight":
                context = build_insight_context(
                    series,
                    entry,
                    ogp_image,
                    draft_flag,
                    sections,
                    hero_image,
                )
                template_name = "post_insight.md.j2"
                slug = f"{base_slug}-insight"
            else:
                context = build_spoiler_context(
                    series,
                    entry,
                    ogp_image,
                    draft_flag,
                    sections,
                    hero_image,
                )
                template_name = "post_spoiler.md.j2"
                slug = base_slug

            # Ensure slug is present in front matter for stable ASCII permalinks
            context["slug"] = slug

            markdown = render_markdown(context, template_name)
            destination = target_markdown_path(series["slug"], published, slug)

            # Skip creating a new file if the slug already exists (avoid duplicate titles)
            if destination.exists():
                log(f"同じタイトルの記事が既に存在するためスキップ: {destination}")
                continue

            try:
                write_markdown_file(destination, markdown)
                log(f"記事を生成しました: {destination}")
            except Exception as exc:  # noqa: BLE001
                log(f"記事書き込みに失敗。draftsへ退避: {exc}")
                backup = fallback_path(series["slug"], slug)
                write_markdown_file(backup, markdown)
                log(f"draftsに保存しました: {backup}")

            processed_hashes.add(unique)
            state.setdefault("entries", []).append(unique)
            new_entries.append(unique)

    # Process feed/manual entries first, then fill from backlog if needed
    for entry in entries:
        if len(new_entries) >= limit:
            break
        process_entry(entry)

    if "glossary" in content_modes:
        write_glossary_post(series, state)

    return new_entries


def write_glossary_post(series: Dict[str, Any], state: Dict[str, Any]) -> None:
    terms = ensure_glossary_terms(series, desired=30)
    if not terms:
        return
    selected, remaining = select_glossary_terms(series["slug"], terms, state)
    context = build_glossary_context(series, selected, remaining)
    context["date"] = dt.datetime.now(dt.timezone.utc).isoformat()
    markdown = render_markdown(context, "post_glossary.md.j2")
    destination = CONTENT_DIR / "posts" / series["slug"] / "glossary.md"
    write_markdown_file(destination, markdown)
    log(f"用語集を更新しました: {destination}")


def main() -> int:
    ensure_directory(CONTENT_DIR / "posts")
    ensure_directory(CONTENT_DIR / "drafts")
    ensure_directory(OGP_DIR)

    state = load_state()
    processed_hashes = set(state.get("entries", []))

    try:
        series_list = load_series_config()
    except FileNotFoundError as exc:
        log(str(exc))
        return 1

    total_new = 0
    per_series_limit = 2  # 各シリーズ2本ずつ
    total_limit = per_series_limit * len(series_list)  # 全シリーズ合計

    for series in series_list:
        if total_new >= total_limit:
            log("Reached daily max; skipping remaining series")
            break
        remaining = total_limit - total_new
        limit_for_series = min(per_series_limit, remaining)
        created = process_series(series, processed_hashes, state, limit=limit_for_series)
        total_new += len(created)

    save_state(state)
    log(f"Generated {total_new} new posts")
    return 0




if __name__ == "__main__":
    raise SystemExit(main())
