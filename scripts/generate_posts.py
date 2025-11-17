from __future__ import annotations

import datetime as dt
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional

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
    load_series_config,
    load_state,
    render_markdown,
    save_state,
    slugify,
    write_markdown_file,
)


def log(message: str) -> None:
    print(f"[generate_posts] {message}")


def target_markdown_path(series_slug: str, published_at: dt.datetime, slug: str) -> Path:
    subdir = CONTENT_DIR / "posts" / series_slug / published_at.strftime("%Y/%m")
    return subdir / f"{slug}.md"


def fallback_path(series_slug: str, slug: str) -> Path:
    return CONTENT_DIR / "drafts" / series_slug / f"{slug}.md"


def try_generate_article(series: Dict[str, Any], entry: Dict[str, Any], mode: str) -> Optional[Dict[str, Any]]:
    try:
        return generate_article_sections(series, entry, mode)
    except Exception as exc:
        log(f"OpenAI縺ｫ繧医ｋ險倅ｺ玖ｦ∫ｴ・函謌舌↓螟ｱ謨・({mode}): {exc}")
        traceback.print_exc()
        return None



def process_series(series: Dict[str, Any], processed_hashes: set[str], state: Dict[str, Any]) -> List[str]:
    new_entries: List[str] = []
    try:
        entries = load_entries_for_series(series, state)
    except Exception as exc:
        log(f"RSS蜿門ｾ励↓螟ｱ謨・ {series['name']} - {exc}")
        traceback.print_exc()
        return new_entries

    content_modes = series.get("content_modes") or ["spoiler"]
    entry_modes = [mode for mode in content_modes if mode != "glossary"]

    def process_entry(entry: Dict[str, Any]) -> None:
        if not entry:
            return
        base_id = entry.get("id", entry.get("title", ""))
        try:
            published = dt.datetime.fromisoformat(entry["date"])
        except Exception:
            published = dt.datetime.now(dt.timezone.utc)

        base_slug = slugify(entry.get("title", f"{series['slug']}-{published:%Y%m%d}"))

        ogp_filename = f"{published:%Y%m%d}_{base_slug}.png"
        ogp_output = OGP_DIR / published.strftime("%Y") / ogp_filename
        try:
            ogp_image = create_ogp_image(
                entry.get("title", series["name"]),
                series["name"],
                entry.get("chapter", ""),
                ogp_output,
            )
        except Exception as exc:
            log(f"OGP逕滂ｿｽE縺ｫ螟ｱ謨・ {exc}")
            ogp_image = None

        draft_flag = bool(series.get("manual")) or not series.get("auto_publish", True)

        hero_image = fetch_pexels_image(entry.get("title", series["name"]))
        target_modes = entry.get("force_modes") or entry_modes

        for mode in target_modes:
            unique = hash_entry(series["slug"], base_id, mode)
            if unique in processed_hashes:
                continue

            sections = try_generate_article(series, entry, mode)
            if mode == "insight":
                context = build_insight_context(series, entry, ogp_image, draft_flag, sections, hero_image)
                template_name = "post_insight.md.j2"
                slug = f"{base_slug}-insight"
            else:
                context = build_spoiler_context(series, entry, ogp_image, draft_flag, sections, hero_image)
                template_name = "post_spoiler.md.j2"
                slug = base_slug

            context["slug"] = slug
            markdown = render_markdown(context, template_name)
            destination = target_markdown_path(series["slug"], published, slug)

            try:
                write_markdown_file(destination, markdown)
                log(f"險倅ｺ九ｒ逕滂ｿｽE縺励∪縺励◆: {destination}")
            except Exception as exc:
                log(f"險倅ｺ区嶌縺崎ｾｼ縺ｿ縺ｫ螟ｱ謨励Ｅrafts縺ｸ騾驕ｿ: {exc}")
                backup = fallback_path(series["slug"], slug)
                write_markdown_file(backup, markdown)
                log(f"drafts縺ｫ菫晏ｭ・ {backup}")

            processed_hashes.add(unique)
            state.setdefault("entries", []).append(unique)
            new_entries.append(unique)

    for entry in entries:
        process_entry(entry)
        if new_entries:
            break

    if not new_entries:
        fallback_entry = select_backlog_entry(series, state)
        if fallback_entry:
            process_entry(fallback_entry)

    if "glossary" in content_modes:
        write_glossary_post(series, state)

    return new_entries

def write_glossary_post(series: Dict[str, Any], state: Dict[str, Any]) -> None:
    terms = load_glossary_terms(series["slug"])
    if not terms:
        return
    selected, remaining = select_glossary_terms(series["slug"], terms, state)
    context = build_glossary_context(series, selected, remaining)
    context["date"] = dt.datetime.now(dt.timezone.utc).isoformat()
    markdown = render_markdown(context, "post_glossary.md.j2")
    destination = CONTENT_DIR / "posts" / series["slug"] / "glossary.md"
    write_markdown_file(destination, markdown)
    log(f"逕ｨ隱樣寔繧呈峩譁ｰ縺励∪縺励◆: {destination}")



def main() -> int:
    ensure_directory(CONTENT_DIR / "posts")
    ensure_directory(CONTENT_DIR / "drafts")
    ensure_directory(OGP_DIR)

    state = load_state()
    today = dt.date.today().isoformat()
    if state.get("last_run_date") == today:
        log("本日の更新は既に実行済みのためスキップします。")
        return 0

    processed_hashes = set(state.get("entries", []))
    processed_hashes |= collect_existing_hashes()

    try:
        series_list = load_series_config()
    except FileNotFoundError as exc:
        log(str(exc))
        return 1

    total_new = 0
    for series in series_list:
        created = process_series(series, processed_hashes, state)
        total_new += len(created)

    state["last_run_date"] = today
    save_state(state)
    log(f"新規生成 {total_new} 記事")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
