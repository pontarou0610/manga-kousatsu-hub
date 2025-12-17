#!/usr/bin/env python3
"""
Main script for generating manga analysis posts.
Reads RSS feeds, generates content using OpenAI, and creates Hugo markdown files.
"""

import os
import json
import yaml
import re
import feedparser
import frontmatter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
from jinja2 import Environment, FileSystemLoader
from unidecode import unidecode

# Import utility functions
from utils import (
    generate_content_with_openai,
    fetch_pexels_image,
    generate_ogp_image,
    generate_hash,
    build_amazon_url,
    build_rakuten_url,
    sanitize_filename
)
from research import collect_reference_notes

# Paths
ROOT_DIR = Path(__file__).parent.parent
DATA_DIR = ROOT_DIR / "data"
CONTENT_DIR = ROOT_DIR / "content" / "posts"
DRAFTS_DIR = ROOT_DIR / "content" / "drafts"
TEMPLATES_DIR = ROOT_DIR / "templates"
STATIC_OGP_DIR = ROOT_DIR / "static" / "ogp"
STATE_FILE = DATA_DIR / "state.json"
SERIES_FILE = DATA_DIR / "series.yaml"
GLOSSARY_DIR = DATA_DIR / "glossary"
BACKLOG_DIR = DATA_DIR / "backlog"

# Initialize Jinja2 environment
jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))

# Runtime controls (cost / throttling)
RSS_MAX_ENTRIES = int(os.getenv("RSS_MAX_ENTRIES", "5"))
MAX_POSTS_PER_RUN = int(os.getenv("MAX_POSTS_PER_RUN", "999"))
MAX_POSTS_PER_SERIES_PER_RUN = int(os.getenv("MAX_POSTS_PER_SERIES_PER_RUN", "999"))
GENERATE_FALLBACK_TOPICS = os.getenv("GENERATE_FALLBACK_TOPICS", "true").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
GENERATE_BACKLOG_ENTRIES = os.getenv("GENERATE_BACKLOG_ENTRIES", "true").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
BACKLOG_ENTRIES_PER_RUN = int(os.getenv("BACKLOG_ENTRIES_PER_RUN", "1"))
GENERATE_SPOILER_POSTS = os.getenv("GENERATE_SPOILER_POSTS", "true").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
GENERATE_INSIGHT_POSTS = os.getenv("GENERATE_INSIGHT_POSTS", "true").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)

def load_state() -> Dict[str, Any]:
    """Load processing state from JSON file."""
    default_state: Dict[str, Any] = {
        "entries": [],
        "glossary_progress": {},
        "backlog_progress": {},
        "chapter_progress": {},
    }
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            try:
                state = json.load(f)
            except json.JSONDecodeError:
                state = {}

        if not isinstance(state, dict):
            state = {}

        # Backward compatible: older caches may miss newer keys.
        for key, value in default_state.items():
            if key not in state or state[key] is None:
                state[key] = value
        if not isinstance(state.get("entries"), list):
            state["entries"] = []
        if not isinstance(state.get("glossary_progress"), dict):
            state["glossary_progress"] = {}
        if not isinstance(state.get("backlog_progress"), dict):
            state["backlog_progress"] = {}
        if not isinstance(state.get("chapter_progress"), dict):
            state["chapter_progress"] = {}

        return state

    return default_state


def save_state(state: Dict[str, Any]) -> None:
    """Save processing state to JSON file."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_series_config() -> List[Dict[str, Any]]:
    """Load series configuration from YAML file."""
    with open(SERIES_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_glossary(series_slug: str) -> List[Dict[str, str]]:
    """Load glossary terms for a series."""
    glossary_file = GLOSSARY_DIR / f"{series_slug}.yaml"
    if glossary_file.exists():
        with open(glossary_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            # New schema (extract_terms.py): {items: [...]}
            # Backward compatible with older {terms: [...]}.
            return data.get('items') or data.get('terms') or []
    return []


def load_backlog(series_slug: str) -> List[Dict[str, Any]]:
    """Load backlog entries for a series (data/backlog/<slug>.yaml)."""
    backlog_file = BACKLOG_DIR / f"{series_slug}.yaml"
    if backlog_file.exists():
        with open(backlog_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            entries = data.get('entries') or data.get('topics') or []
            return entries
    return []


def parse_rfc3339(dt_str: str) -> datetime:
    # Accept "...Z" and without timezone.
    if not dt_str:
        return datetime.utcnow()
    dt_str = dt_str.strip()
    if dt_str.endswith("Z"):
        dt_str = dt_str[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(dt_str)
    except ValueError:
        return datetime.utcnow()


def format_rfc3339(dt: datetime) -> str:
    # Ensure we always output timezone-aware timestamps.
    if dt.tzinfo is None:
        return dt.replace(microsecond=0).isoformat() + "Z"
    return dt.replace(microsecond=0).isoformat()


JST = timezone(timedelta(hours=9))


def extract_chapter_number(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value)
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None


def normalize_chapter_label(series_slug: str, chapter_number: int, raw: str) -> str:
    raw = (raw or "").strip()
    if extract_chapter_number(raw) is not None:
        return raw
    # Fallback: default Japanese chapter label.
    return f"第{chapter_number}話"


def build_post_slug(series_slug: str, chapter_number: int, yyyymmdd: str, variant: str) -> str:
    base = f"{series_slug}-di-{chapter_number}hua-netaharekao-cha-{yyyymmdd}"
    if variant == "insight":
        return f"{base}-insight"
    return base


def build_post_output_path(series_slug: str, dt: datetime, slug: str) -> Path:
    year = dt.year
    month = dt.month
    return CONTENT_DIR / series_slug / f"{year:04d}" / f"{month:02d}" / f"{slug}.md"


def build_post_url(dt: datetime, slug: str) -> str:
    return f"/posts/{dt.year:04d}/{dt.month:02d}/{slug}/"


def get_prev_post(series_slug: str, chapter_number: int) -> Optional[Dict[str, str]]:
    # Find the most recent spoiler post with smaller chapter_number.
    candidates = []
    series_root = CONTENT_DIR / series_slug
    if not series_root.exists():
        return None
    for path in series_root.rglob("*.md"):
        if "glossary" in path.parts:
            continue
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.get("article_variant") != "spoiler":
            continue
        prev_ch_num = extract_chapter_number(post.get("chapter"))
        if prev_ch_num is None or prev_ch_num >= chapter_number:
            continue
        post_date = parse_rfc3339(str(post.get("date") or ""))
        candidates.append((prev_ch_num, post_date, post.get("title") or "", post.get("slug") or ""))

    if not candidates:
        return None

    candidates.sort(key=lambda x: (x[0], x[1]))
    _, dt, title, slug = candidates[-1]
    return {"title": title, "url": build_post_url(dt, slug)}


def has_existing_variant_post(series_slug: str, variant: str, chapter_number: int) -> bool:
    if not chapter_number or chapter_number < 0:
        return False

    series_root = CONTENT_DIR / series_slug
    if not series_root.exists():
        return False

    for path in series_root.rglob("*.md"):
        if "glossary" in path.parts:
            continue
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if post.get("article_variant") != variant:
            continue
        post_ch = extract_chapter_number(post.get("chapter"))
        if post_ch == chapter_number:
            return True

    return False


def get_max_variant_chapter(series_slug: str, variant: str) -> int:
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
        if ch is not None and ch > max_ch:
            max_ch = ch

    return max_ch


def get_last_generated_chapter(state: Dict[str, Any], series_slug: str, variant: str) -> int:
    progress = state.get("chapter_progress", {}).get(series_slug)
    if isinstance(progress, int) and progress > 0:
        return progress
    return get_max_variant_chapter(series_slug, variant)


def set_last_generated_chapter(state: Dict[str, Any], series_slug: str, chapter_number: int) -> None:
    if chapter_number is None:
        return
    if "chapter_progress" not in state or not isinstance(state.get("chapter_progress"), dict):
        state["chapter_progress"] = {}
    prev = state["chapter_progress"].get(series_slug)
    if isinstance(prev, int):
        state["chapter_progress"][series_slug] = max(prev, int(chapter_number))
    else:
        state["chapter_progress"][series_slug] = int(chapter_number)


def ensure_ogp(series_name: str, title: str, dt: datetime, slug: str) -> List[str]:
    yyyymmdd = f"{dt.year:04d}{dt.month:02d}{dt.day:02d}"
    rel = f"ogp/{dt.year:04d}/{yyyymmdd}_{slug}.png"
    out = STATIC_OGP_DIR / f"{dt.year:04d}" / f"{yyyymmdd}_{slug}.png"
    generate_ogp_image(title=title, series=series_name, output_path=out)
    return [rel]


def create_spoiler_post(
    series: Dict[str, Any],
    chapter_label: str,
    chapter_number: int,
    dt: datetime,
    content: Dict[str, Any],
    reference_links: Optional[List[Dict[str, str]]] = None,
) -> Optional[Path]:
    series_slug = series["slug"]
    yyyymmdd = f"{dt.year:04d}{dt.month:02d}{dt.day:02d}"
    slug = build_post_slug(series_slug, chapter_number, yyyymmdd, variant="spoiler")
    output_path = build_post_output_path(series_slug, dt, slug)

    if has_existing_variant_post(series_slug, "spoiler", chapter_number):
        return None
    if output_path.exists():
        return None

    affiliate_ids = {
        "amazon": build_amazon_url(series.get("affiliates", {}).get("amazon", {}).get("asin", "")),
        "rakuten": build_rakuten_url(series.get("affiliates", {}).get("rakuten", {}).get("params", "")),
        "others": series.get("affiliates", {}).get("others", []) or [],
    }

    title = content.get("title") or f"{series['name']} {chapter_label} ネタバレ・感想・考察"
    images = ensure_ogp(series["name"], title, dt, slug)

    context = {
        "title": title,
        "slug": slug,
        "date": format_rfc3339(dt),
        "series": series["name"],
        "series_slug": series_slug,
        "chapter": chapter_label,
        "chapter_label": chapter_label,
        "tags": series.get("tags", []),
        "draft": (not bool(series.get("auto_publish", True))),
        "description": (content.get("intro") or title)[:140],
        "affiliate_ids": affiliate_ids,
        "disclaimer": series.get("defaults", {}).get("disclaimer", ""),
        "images": images,
        "intro": content.get("intro") or "",
        "summary_points": content.get("summary_points") or [],
        "spoiler": content.get("spoiler") or {},
        "prev_post": get_prev_post(series_slug, chapter_number),
        "official_link": (series.get("official_links") or [None])[0],
        "reference_links": reference_links or [],
    }

    ok = create_post_from_template("post_spoiler.md.j2", context, output_path, is_draft=context["draft"])
    return output_path if ok else None


def create_insight_post(series: Dict[str, Any], chapter_label: str, chapter_number: int, dt: datetime, content: Dict[str, Any]) -> Optional[Path]:
    series_slug = series["slug"]
    yyyymmdd = f"{dt.year:04d}{dt.month:02d}{dt.day:02d}"
    slug = build_post_slug(series_slug, chapter_number, yyyymmdd, variant="insight")
    output_path = build_post_output_path(series_slug, dt, slug)

    if has_existing_variant_post(series_slug, "insight", chapter_number):
        return None
    if output_path.exists():
        return None

    affiliate_ids = {
        "amazon": build_amazon_url(series.get("affiliates", {}).get("amazon", {}).get("asin", "")),
        "rakuten": build_rakuten_url(series.get("affiliates", {}).get("rakuten", {}).get("params", "")),
        "others": series.get("affiliates", {}).get("others", []) or [],
    }

    title = content.get("title") or f"{series['name']} {chapter_label} 考察"
    images = ensure_ogp(series["name"], title, dt, slug)

    context = {
        "title": title,
        "slug": slug,
        "date": format_rfc3339(dt),
        "series": series["name"],
        "chapter": chapter_label,
        "tags": series.get("tags", []),
        "draft": (not bool(series.get("auto_publish", True))),
        "description": (content.get("intro") or title)[:140],
        "affiliate_ids": affiliate_ids,
        "disclaimer": series.get("defaults", {}).get("disclaimer", ""),
        "images": images,
        "intro": content.get("intro") or "",
        "summary_points": content.get("summary_points") or [],
        "insight": content.get("insight") or {},
        "outline": content.get("outline") or [],
        "faq": content.get("faq") or [],
        "hero_image": None,
        "reference_links": [],
        "official_link": (series.get("official_links") or [None])[0],
    }

    ok = create_post_from_template("post_insight.md.j2", context, output_path, is_draft=context["draft"])
    return output_path if ok else None


def generate_spoiler_content(
    series: Dict[str, Any],
    chapter: str,
    reference_notes: Optional[List[Dict[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    """Generate spoiler content using OpenAI."""
    system_prompt = f"""あなたは「{series['name']}」の考察記事を書く専門家です。
{series.get('defaults', {}).get('tone', '落ち着いた敬体で、根拠を示しつつ丁寧にまとめる。')}
{series.get('defaults', {}).get('prohibited', '誹謗中傷や憶測だけの断定、暴力的・過激な表現は避ける。')}

【重要な文章作成ルール】
- 句点（。）の後は必ず改行してください
- 1文を短く簡潔にまとめ、読みやすさを最優先してください
- 長い文章は避け、適切な長さで区切ってください"""

    refs_block = ""
    if reference_notes:
        lines = []
        for ref in reference_notes[:8]:
            title = (ref.get("title") or "").strip()
            url = (ref.get("url") or "").strip()
            desc = (ref.get("desc") or "").strip()
            src = (ref.get("source") or "").strip()
            if not url:
                continue
            line = f"- {title} ({src}) {url}"
            if desc:
                line += f" / 概要: {desc}"
            lines.append(line)
        if lines:
            refs_block = (
                "\n\n【参考メモ（外部サイト）】\n"
                "※以下は見出し/概要のみです。本文の引用・言い換えは禁止。事実関係の確認と論点整理の参考にのみ使ってください。\n"
                + "\n".join(lines)
            )

    prompt = f"""「{series['name']}」の{chapter}について、ネタバレありの考察記事を作成してください。

以下のJSON形式で出力してください：
{{
  "title": "記事タイトル（ネタバレ注意を含む）",
  "intro": "導入文（ネタバレなし、200文字程度）",
  "summary_points": ["ポイント1", "ポイント2", "ポイント3"],
  "spoiler": {{
    "synopsis": "あらすじ要約（300文字程度、句点の後は改行）",
    "foreshadowings": ["伏線1（句点の後は改行）", "伏線2（句点の後は改行）", "伏線3（句点の後は改行）"],
    "predictions": ["予想1（根拠付き、句点の後は改行）", "予想2（根拠付き、句点の後は改行）"]
  }}
}}

※すべてのテキストフィールドで、句点（。）の後は必ず改行（\n）を入れてください。{refs_block}"""

    return generate_content_with_openai(
        prompt=prompt,
        system_prompt=system_prompt,
        response_format={"type": "json_object"}
    )


def generate_insight_content(series: Dict[str, Any], topic: str) -> Optional[Dict[str, Any]]:
    """Generate insight content (no spoilers) using OpenAI."""
    system_prompt = f"""あなたは「{series['name']}」の考察記事を書く専門家です。
ネタバレを避け、テーマに沿った分析を提供してください。
{series.get('defaults', {}).get('tone', '落ち着いた敬体で、根拠を示しつつ丁寧にまとめる。')}

【重要な文章作成ルール】
- 句点（。）の後は必ず改行してください
- 1文を短く簡潔にまとめ、読みやすさを最優先してください
- 長い文章は避け、適切な長さで区切ってください"""

    prompt = f"""「{series['name']}」について、以下のテーマでネタバレなしの考察記事を作成してください：
テーマ: {topic}

以下のJSON形式で出力してください：
{{
  "title": "記事タイトル",
  "intro": "導入文（200文字程度、句点の後は改行）",
  "summary_points": ["ポイント1（句点の後は改行）", "ポイント2（句点の後は改行）", "ポイント3（句点の後は改行）"],
  "insight": {{
    "themes": [
      {{"title": "テーマ1", "detail": "詳細説明（句点の後は改行）"}},
      {{"title": "テーマ2", "detail": "詳細説明（句点の後は改行）"}}
    ],
    "characters": [
      {{"name": "キャラクター名", "focus": "着眼点（句点の後は改行）"}}
    ]
  }},
  "outline": [
    {{"heading": "見出し1", "bullets": ["項目1（句点の後は改行）", "項目2（句点の後は改行）"]}}
  ],
  "faq": [
    {{"question": "質問1", "answer": "回答1（句点の後は改行）"}},
    {{"question": "質問2", "answer": "回答2（句点の後は改行）"}}
  ]
}}

※すべてのテキストフィールドで、句点（。）の後は必ず改行（\n）を入れてください。"""

    return generate_content_with_openai(
        prompt=prompt,
        system_prompt=system_prompt,
        response_format={"type": "json_object"}
    )


def create_post_from_template(
    template_name: str,
    context: Dict[str, Any],
    output_path: Path,
    is_draft: bool = False
) -> bool:
    """Create a post file from Jinja2 template."""
    try:
        template = jinja_env.get_template(template_name)
        content = template.render(**context)
        
        # Create output directory
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        status = "draft" if is_draft else "post"
        print(f"[OK] Created {status}: {output_path.name}")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error creating post: {e}")
        return False


def generate_glossary_post(series: Dict[str, Any], state: Dict[str, Any]) -> None:
    """Generate or update glossary post for a series."""
    series_slug = series['slug']
    glossary_terms = load_glossary(series_slug)
    
    if not glossary_terms:
        print(f">> No glossary terms for {series['name']}")
        return

    # Always publish all terms. Only rewrite when the rendered content changes.
    terms_to_publish = glossary_terms

    # Output path
    output_dir = CONTENT_DIR / series_slug / "glossary"
    output_path = output_dir / "index.md"

    # Keep existing date to avoid rewriting the file every run.
    existing_date = None
    if output_path.exists():
        try:
            post = frontmatter.load(output_path)
            existing_date = post.get("date")
        except Exception:
            existing_date = None

    if isinstance(existing_date, datetime):
        existing_date = existing_date.astimezone(JST).replace(microsecond=0).isoformat()
    elif isinstance(existing_date, str):
        existing_date = existing_date.strip() or None

    date_value = existing_date or datetime.now(tz=JST).replace(microsecond=0).isoformat()
    
    # Prepare context
    context = {
        'title': f"{series['name']} 用語集",
        'date': date_value,
        'series': series['name'],
        'series_slug': series_slug,
        'tags': series.get('tags', []),
        'intro': f"{series['name']}に登場する重要な用語をまとめました。",
        'glossary': terms_to_publish,
        'glossary_note': "用語は随時追加されます。",
        'affiliate_ids': {
            'amazon': build_amazon_url(series.get('affiliates', {}).get('amazon', {}).get('asin', '')),
            'rakuten': build_rakuten_url(series.get('affiliates', {}).get('rakuten', {}).get('params', '')),
            'others': series.get('affiliates', {}).get('others', [])
        },
        'affiliate_widgets': {
            'amazon': build_amazon_url(series.get('affiliates', {}).get('amazon', {}).get('asin', ''))
        },
        'disclaimer': series.get('defaults', {}).get('disclaimer', ''),
        'official_link': series.get('official_links', [{}])[0] if series.get('official_links') else None
    }

    try:
        template = jinja_env.get_template('post_glossary.md.j2')
        content = template.render(**context)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        existing = output_path.read_text(encoding='utf-8') if output_path.exists() else None

        if existing == content:
            print(f">> Glossary unchanged for {series['name']}")
            return

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"[OK] Updated glossary: {len(terms_to_publish)} terms")

    except Exception as e:
        print(f"[ERROR] Error creating glossary post: {e}")
        return


def process_series(series: Dict[str, Any], state: Dict[str, Any], remaining_posts: int) -> int:
    """Process a single series: check RSS, generate posts."""
    print(f"\n>> Processing: {series['name']}")
    
    # Generate glossary if enabled
    if 'glossary' in series.get('content_modes', []):
        generate_glossary_post(series, state)
    
    entries_set = set(state.get("entries", []))
    created_posts = 0

    # Check RSS feed
    if series.get('rss'):
        feed = feedparser.parse(series['rss'])
        rss_mode = (series.get("rss_mode") or "chapter_from_title").strip()

        # Process oldest-first so we can "catch up" gradually.
        candidates = []
        for entry in getattr(feed, "entries", [])[:50]:
            entry_hash = generate_hash((getattr(entry, "link", "") or "") + (getattr(entry, "title", "") or ""))
            if entry_hash in entries_set:
                continue
            published = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
            dt = parse_rfc3339(published)
            candidates.append((dt, entry, entry_hash))

        candidates.sort(key=lambda x: x[0])
        for dt, entry, entry_hash in candidates[:RSS_MAX_ENTRIES]:
            if remaining_posts <= created_posts:
                break

            print(f"[NEW] New entry: {entry.title}")

            if rss_mode == "signal_only":
                # Treat any new RSS item as a "new chapter signal".
                last = get_last_generated_chapter(state, series["slug"], variant="spoiler")
                chapter_number = last + 1
                chapter_label = f"第{chapter_number}話"
            else:
                chapter_number = extract_chapter_number(entry.title)
                if chapter_number is None:
                    # Fallback: put it in a reasonable bucket.
                    chapter_number = 0
                chapter_label = normalize_chapter_label(series["slug"], chapter_number, str(entry.title))

            created_any = False
            if GENERATE_SPOILER_POSTS and 'spoiler' in series.get('content_modes', []):
                if remaining_posts <= created_posts:
                    break
                if chapter_number and has_existing_variant_post(series["slug"], "spoiler", chapter_number):
                    # Consider this RSS item "handled" if the post already exists.
                    state["entries"].append(entry_hash)
                    entries_set.add(entry_hash)
                    set_last_generated_chapter(state, series["slug"], chapter_number)
                    created_any = True
                    print(f">> RSS spoiler already exists for {series['slug']} #{chapter_number}")
                else:
                    ref_sources = series.get("research_sources") or []
                    reference_notes = collect_reference_notes(
                        series_name=series["name"],
                        chapter_label=chapter_label,
                        sources=ref_sources,
                    ) if ref_sources else []

                    content = generate_spoiler_content(series, chapter_label, reference_notes=reference_notes)
                    if content and create_spoiler_post(
                        series,
                        chapter_label,
                        chapter_number,
                        dt,
                        content,
                        reference_links=reference_notes,
                    ):
                        created_posts += 1
                        created_any = True
                        set_last_generated_chapter(state, series["slug"], chapter_number)

            if GENERATE_INSIGHT_POSTS and 'insight' in series.get('content_modes', []):
                if remaining_posts <= created_posts:
                    break
                if chapter_number and has_existing_variant_post(series["slug"], "insight", chapter_number):
                    state["entries"].append(entry_hash)
                    entries_set.add(entry_hash)
                    set_last_generated_chapter(state, series["slug"], chapter_number)
                    created_any = True
                    print(f">> RSS insight already exists for {series['slug']} #{chapter_number}")
                else:
                    content = generate_insight_content(series, str(entry.title))
                    if content and create_insight_post(series, chapter_label, chapter_number, dt, content):
                        created_posts += 1
                        created_any = True
                        set_last_generated_chapter(state, series["slug"], chapter_number)

            if created_any:
                if entry_hash not in entries_set:
                    state['entries'].append(entry_hash)
                    entries_set.add(entry_hash)
            else:
                print(f"[WARN] No post generated for RSS entry (will retry): {entry.title}")
    
    # Process fallback topics if no RSS or no new entries
    fallback_topics = series.get('fallback_topics', [])
    if GENERATE_FALLBACK_TOPICS and fallback_topics and 'insight' in series.get('content_modes', []):
        progress = state['backlog_progress'].get(series['slug'], 0)
        
        if progress < len(fallback_topics):
            topic = fallback_topics[progress]
            print(f"[INFO] Generating fallback insight: {topic}")
            
            content = generate_insight_content(series, topic)
            if content:
                # TODO: Create insight post from fallback topic
                state['backlog_progress'][series['slug']] = progress + 1

    # Process structured backlog entries (daily catch-up).
    if GENERATE_BACKLOG_ENTRIES and remaining_posts > created_posts:
        backlog_entries = load_backlog(series["slug"])
        if backlog_entries:
            pending = []
            for item in backlog_entries:
                ch_num = extract_chapter_number(item.get("chapter_number") or item.get("chapter") or item.get("title"))
                if ch_num is None:
                    continue

                modes = item.get("force_modes") or []
                if not isinstance(modes, list):
                    modes = []

                # Backward compatible: older key format used the joined force_modes list.
                old_key = generate_hash(f"backlog:{series['slug']}:{ch_num}:{','.join(modes)}")
                if old_key in entries_set:
                    continue

                # Only consider modes that are enabled for this run.
                actionable_modes: List[str] = []
                for mode in modes:
                    if mode == "spoiler" and GENERATE_SPOILER_POSTS and "spoiler" in series.get("content_modes", []):
                        actionable_modes.append(mode)
                    elif mode == "insight" and GENERATE_INSIGHT_POSTS and "insight" in series.get("content_modes", []):
                        actionable_modes.append(mode)

                # If no actionable modes (e.g. insight-only entry but insight generation disabled), skip for now.
                if not actionable_modes:
                    continue

                keys_by_mode = {mode: generate_hash(f"backlog:{series['slug']}:{ch_num}:{mode}") for mode in actionable_modes}
                if all(k in entries_set for k in keys_by_mode.values()):
                    continue

                dt = parse_rfc3339(str(item.get("date") or ""))
                pending.append((dt, ch_num, item, keys_by_mode))

            pending.sort(key=lambda x: (x[0], x[1]))
            for dt, ch_num, item, keys_by_mode in pending[:BACKLOG_ENTRIES_PER_RUN]:
                if remaining_posts <= created_posts:
                    break
                chapter_label = normalize_chapter_label(series["slug"], ch_num, str(item.get("chapter") or ""))

                created_any = False
                if "spoiler" in keys_by_mode and GENERATE_SPOILER_POSTS and "spoiler" in series.get("content_modes", []):
                    if remaining_posts <= created_posts:
                        break
                    key = keys_by_mode["spoiler"]
                    if key in entries_set:
                        pass
                    elif has_existing_variant_post(series["slug"], "spoiler", ch_num):
                        state["entries"].append(key)
                        entries_set.add(key)
                        set_last_generated_chapter(state, series["slug"], ch_num)
                        created_any = True
                        print(f">> Backlog spoiler already exists for {series['slug']} #{ch_num}")
                    else:
                        ref_sources = series.get("research_sources") or []
                        reference_notes = collect_reference_notes(
                            series_name=series["name"],
                            chapter_label=chapter_label,
                            sources=ref_sources,
                        ) if ref_sources else []

                        content = generate_spoiler_content(series, chapter_label, reference_notes=reference_notes)
                        if content and create_spoiler_post(
                            series,
                            chapter_label,
                            ch_num,
                            dt,
                            content,
                            reference_links=reference_notes,
                        ):
                            state["entries"].append(key)
                            entries_set.add(key)
                            created_posts += 1
                            created_any = True
                            set_last_generated_chapter(state, series["slug"], ch_num)

                if "insight" in keys_by_mode and GENERATE_INSIGHT_POSTS and "insight" in series.get("content_modes", []):
                    if remaining_posts <= created_posts:
                        break
                    key = keys_by_mode["insight"]
                    if key in entries_set:
                        pass
                    elif has_existing_variant_post(series["slug"], "insight", ch_num):
                        state["entries"].append(key)
                        entries_set.add(key)
                        set_last_generated_chapter(state, series["slug"], ch_num)
                        created_any = True
                        print(f">> Backlog insight already exists for {series['slug']} #{ch_num}")
                    else:
                        topic = str(item.get("title") or chapter_label)
                        content = generate_insight_content(series, topic)
                        if content and create_insight_post(series, chapter_label, ch_num, dt, content):
                            state["entries"].append(key)
                            entries_set.add(key)
                            created_posts += 1
                            created_any = True
                            set_last_generated_chapter(state, series["slug"], ch_num)

                if not created_any:
                    # Keep it pending for next run (e.g., API error).
                    print(f"[WARN] No post generated for backlog entry (will retry): {series['slug']} #{ch_num}")

    return created_posts


def main():
    """Main execution function."""
    print(">> Starting post generation...")
    
    # Load configuration and state
    series_list = load_series_config()
    series_list = sorted(series_list, key=lambda s: int(s.get("run_priority", 999)))
    state = load_state()
    remaining_posts = MAX_POSTS_PER_RUN
    
    # Process each series
    for series in series_list:
        if series.get('manual', False):
            print(f">> Skipping manual series: {series['name']}")
            continue
        if remaining_posts <= 0:
            break
        
        try:
            series_budget = min(remaining_posts, MAX_POSTS_PER_SERIES_PER_RUN)
            created = process_series(series, state, series_budget)
            remaining_posts -= int(created or 0)
        except Exception as e:
            print(f"[ERROR] Error processing {series['name']}: {e}")
            continue
    
    # Save state
    save_state(state)
    print("\n>> Post generation complete!")


if __name__ == "__main__":
    main()
