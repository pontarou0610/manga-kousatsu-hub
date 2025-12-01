from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from string import Template
import unicodedata

import feedparser
import frontmatter
import openai
import requests
import yaml
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageDraw, ImageFont

try:
    from unidecode import unidecode
except ImportError:
    unidecode = None

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONTENT_DIR = ROOT_DIR / "content"
TEMPLATE_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
OGP_DIR = STATIC_DIR / "ogp"
GLOSSARY_DIR = DATA_DIR / "glossary"
BACKLOG_DIR = DATA_DIR / "backlog"

OGP_WIDTH = 1200
OGP_HEIGHT = 630
OGP_BG = "#090a13"
OGP_ACCENT = "#ff5c7b"
FONT_PATH = ROOT_DIR / "assets" / "fonts" / "NotoSansJP-Regular.ttf"

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PEXELS_API_ENDPOINT = "https://api.pexels.com/v1/search"
AMAZON_TAG = os.getenv("AMAZON_TAG")
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY

JINJA_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(
        disabled_extensions=("md",),
        default_for_string=False,
        default=False,
    ),
    trim_blocks=True,
    lstrip_blocks=True,
)

ARTICLE_SYSTEM_PROMPT_SPOILER = """
You are a Japanese manga spoiler writer. Always cover the latest chapter first; if unavailable, start from chapter 1 in order.
Write detailed chronological spoilers with key events, quotes, character feelings, foreshadowings (3-4), and predictions (2-3 with reasoning).
Keep Japanese output natural. Add 1-3 glossary items (new terms preferred; otherwise enrich existing).
"""

ARTICLE_SYSTEM_PROMPT_INSIGHT = (
    "You are a spoiler-free analysis writer in Japanese. "
    "Avoid core spoilers, highlight themes and character motives with concrete examples. "
    "Keep the tone friendly and curious so readers want the next chapter."
)

ARTICLE_REVIEW_SYSTEM = (
    "You are a QA checker. Validate the given JSON, fix omissions, and return only corrected JSON."
)

ARTICLE_SPOILER_USER_TMPL = Template("""
Use the following context to produce JSON for a manga spoiler article.

# Series Info
- Title: $series_name
- Chapter: $chapter
- Entry title: $entry_title
- RSS summary: $entry_summary
- Official links (up to 3):
$official_links

# Output
Return JSON with keys: title, intro, summary_points, spoiler, glossary_updates, reference_links.
1. title: SEO-friendly Japanese title ~32 chars that includes series + chapter + "最新話ネタバレ・感想・考察".
2. intro: 90-160 Japanese chars. Mention the chapter, include a soft warning that spoilers follow, and keep the tone friendly.
3. summary_points: 3 bullet strings (spoiler-free) that give a quick chronological outline of the chapter.
4. spoiler: {
     "synopsis": >=1500 Japanese characters, chronological and detailed, mixing key lines/actions with brief first-person reactions,
     "foreshadowings": 3-4 bullet strings focusing on伏線・謎・キャラの変化,
     "predictions": 2 bullet strings for 今後の予想 with explicit reasoning and "予想" wording.
   }
5. glossary_updates: 1-3 items { "term": "...", "reading": optional, "description": "作品を知らない人にもわかる1-3文" }.
   - Prefer new terms/abilities/技/場所 from this chapter; if none, lightly enrich an existing term.
6. reference_links: only from provided list. Each item { "label": "...", "url": "..." }.

Return JSON only.
""")
ARTICLE_SPOILER_REVIEW_TMPL = """Validate and fix this JSON for a blog spoiler. If synopsis < 1500 chars, extend it. Return only JSON.

{raw}

"""
ARTICLE_INSIGHT_USER_TMPL = Template("""
Use the following context to produce spoiler-free analysis JSON.

# Series Info
- Title: $series_name
- Chapter: $chapter
- Entry title: $entry_title
- RSS summary: $entry_summary
- Official links (up to 3):
$official_links

# Output
Keys: intro, summary_points, themes, characters, reference_links, title.
1. intro: 120-180 chars, spoiler-free, setting up the question to explore in a casual tone.
2. summary_points: 3 bullet strings (each >=80 Japanese chars) highlighting insights, not just plot.
3. themes: 3 items { "title": "...", "detail": "... (>=200 chars with concrete examples)" }.
4. characters: 3 items { "name": "...", "focus": "... (explain inner conflict / motive / consequence)" }.
5. reference_links: only provided official links.
6. title: SEO friendly Japanese title (~30 chars) including series + topic.

Return JSON only.
""")
ARTICLE_INSIGHT_REVIEW_TMPL = """Validate and fix this JSON for a spoiler-free analysis. Return only corrected JSON.

{raw}
"""

ARTICLE_INSIGHT_SYSTEM_EXTRA = (
    "Keep output concise and readable. Add concrete examples and reasons, not just abstractions. "
    "Leave a bit of curiosity so readers want the next chapter."
)

GLOSSARY_SYSTEM_PROMPT = (
    "Create a manga glossary in Japanese. Add 1-3 terms (skills/places/organizations) relevant to this article. "
    "40-80 chars per item. Return JSON: {"term":"...","reading":"...","description":"...","reference":"..."}"
)

def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_series_config(path: Path = DATA_DIR / "series.yaml") -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"series設定ファイルが見つかりません: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_state(path: Path = DATA_DIR / "state.json") -> Dict[str, Any]:
    if not path.exists():
        return {"entries": [], "glossary_progress": {}, "backlog_progress": {}}
    with path.open(encoding="utf-8") as f:
        try:
            state = json.load(f)
        except json.JSONDecodeError:
            state = {"entries": []}
    if "entries" not in state:
        state["entries"] = []
    if "glossary_progress" not in state:
        state["glossary_progress"] = {}
    if "backlog_progress" not in state:
        state["backlog_progress"] = {}
    return state


def save_state(state: Dict[str, Any], path: Path = DATA_DIR / "state.json") -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def slugify(value: str) -> str:
    """
    Convert arbitrary text into an ASCII-only slug suitable for permalinks.

    Japanese titles (and other non-Latin scripts) are transliterated when
    possible; otherwise we fall back to a stable hash to keep URLs deterministic.
    """
    if not value:
        return "post"

    normalized = unicodedata.normalize("NFKD", value)
    transliterated = unidecode(normalized) if unidecode else normalized
    ascii_value = transliterated.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^\w\s-]", "", ascii_value)
    ascii_value = re.sub(r"[\s_-]+", "-", ascii_value).strip("-")
    if ascii_value:
        return ascii_value

    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"post-{digest}"


def hash_entry(*parts: str) -> str:
    joined = "::".join(parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def fetch_feed(url: str) -> Iterable[feedparser.FeedParserDict]:
    if not url:
        return []
    headers = {
        "User-Agent": "manga-kousatsu-hub-bot (+https://github.com/pontarou0610/manga-kousatsu-hub)",
    }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    parsed = feedparser.parse(response.content)
    return parsed.entries


def collect_existing_hashes(content_root: Path = CONTENT_DIR) -> set[str]:
    hashes: set[str] = set()
    if not content_root.exists():
        return hashes
    for md_file in content_root.rglob("*.md"):
        try:
            post = frontmatter.load(md_file)
        except Exception:
            continue
        meta = post.metadata or {}
        base = f"{meta.get('series','')}-{meta.get('title','')}-{meta.get('date','')}-{meta.get('article_variant','')}"
        hashes.add(hash_entry(base))
    return hashes


def render_markdown(context: Dict[str, Any], template_name: str) -> str:
    template = JINJA_ENV.get_template(template_name)
    return template.render(**context)


def create_ogp_image(title: str, series: str, chapter: str, output_path: Path) -> str:
    ensure_directory(output_path.parent)
    canvas = Image.new("RGB", (OGP_WIDTH, OGP_HEIGHT), OGP_BG)
    draw = ImageDraw.Draw(canvas)
    font_title = ImageFont.load_default()
    font_meta = ImageFont.load_default()
    if FONT_PATH.exists():
        try:
            font_title = ImageFont.truetype(str(FONT_PATH), size=40)
            font_meta = ImageFont.truetype(str(FONT_PATH), size=28)
        except Exception:
            font_title = ImageFont.load_default()
            font_meta = ImageFont.load_default()

    def text_width(text: str, font) -> int:
        bbox = draw.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0]

    def draw_text(text: str, xy: Tuple[int, int], font, max_width: int, line_height: int) -> None:
        words = text.split()
        line = ""
        x, y = xy
        for word in words:
            test_line = (line + " " + word).strip()
            w = text_width(test_line, font)
            if w > max_width and line:
                draw.text((x, y), line, font=font, fill="#f4f6fb")
                line = word
                y += line_height
            else:
                line = test_line
        if line:
            draw.text((x, y), line, font=font, fill="#f4f6fb")

    draw.rectangle([(50, 50), (1150, 580)], outline=OGP_ACCENT, width=4)
    draw.text((80, 90), series, font=font_meta, fill=OGP_ACCENT)
    chapter_label = f"{chapter}考察" if chapter else "考察アップデート"
    draw.text((80, 140), chapter_label, font=font_meta, fill="#ffffff")
    draw_text(title, (80, 200), font_title, max_width=1040, line_height=32)
    draw.text((80, 540), "manga-kousatsu-hub", font=font_meta, fill="#ffffff")

    canvas.save(output_path)
    rel_path = output_path.relative_to(STATIC_DIR).as_posix()
    return rel_path


def fetch_pexels_image(query: str) -> Optional[Dict[str, str]]:
    if not PEXELS_API_KEY:
        return None
    headers = {"Authorization": PEXELS_API_KEY}
    params = {
        "query": re.sub(r"\s+", " ", query).strip()[:80] or "manga illustration",
        "per_page": 1,
        "orientation": "landscape",
    }
    try:
        resp = requests.get(PEXELS_API_ENDPOINT, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return None
    photos = data.get("photos") or []
    if not photos:
        return None
    photo = photos[0]
    src = photo.get("src") or {}
    image_url = src.get("landscape") or src.get("large") or src.get("medium")
    if not image_url:
        return None

    return {
        "url": image_url,
        "alt": photo.get("alt") or query,
        "photographer": photo.get("photographer") or "Pexels",
        "photographer_url": photo.get("photographer_url") or photo.get("url"),
        "pexels_url": photo.get("url"),
    }


def build_affiliate_urls(series: Dict[str, Any]) -> Dict[str, str]:
    amazon_asin = series.get("affiliates", {}).get("amazon", {}).get("asin", "")
    rakuten_params = series.get("affiliates", {}).get("rakuten", {}).get("params", "YOUR_RAKUTEN_PARAMS")
    amazon_tag = (
        series.get("affiliates", {}).get("amazon", {}).get("tag")
        or AMAZON_TAG
        or "YOUR_AMAZON_TAG"
    )
    amazon_url = (
        if amazon_asin and amazon_tag
        else ""
    )
    return {
        "amazon": amazon_url,
        "rakuten": rakuten_url,
    }


def prioritized_other_affiliates(series: Dict[str, Any]) -> List[Dict[str, str]]:
    affiliates = series.get("affiliates", {})
    others = affiliates.get("others", []) or []
    priority = affiliates.get("priority") or []
    if not priority:
        return others
    priority_map = {name: index for index, name in enumerate(priority)}
    return sorted(
        others,
        key=lambda item: priority_map.get(item.get("name"), len(priority_map)),
    )


def default_summary_points(series_name: str, chapter_title: str) -> List[str]:
    return [
        f"{series_name}最新話「{chapter_title}」の見どころをネタバレ無しで3行まとめ。",
        "重要な伏線・考察はネタバレトグル内に集約し、読みたくない人も安心。",
        "引用は最小限・公式情報のみを参照し、二次利用ガイドラインを遵守。",
    ]


def _call_openai(system_prompt: str, user_prompt: str, temperature: float = 0.6) -> Optional[str]:
    if not OPENAI_API_KEY:
        return None
    last_error: Optional[Exception] = None
    for attempt in range(3):
        try:
            resp = openai.chat.completions.create(
                model=OPENAI_MODEL,
                temperature=temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            return (resp.choices[0].message.content or "").strip()
        except Exception as exc:
            last_error = exc
            sleep_for = min(8, 2 ** attempt)
            time.sleep(sleep_for)
    return None


def _extract_json_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text.strip("` ")
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        candidate = match.group(0).strip("` \n")
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate
    return None


def _normalize_spoiler_payload(data: Dict[str, Any], official_links: List[Dict[str, str]]) -> Dict[str, Any]:
    def clean_list(value: Any) -> List[str]:
        items: List[str] = []
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    text = entry.strip()
                    if text:
                        items.append(text)
        return items

    summary_points = clean_list(data.get("summary_points"))[:3]
    if not summary_points:
        summary_points = [
            "公開済み情報のみで最新話の見どころを整理。",
            "伏線・新情報はネタバレトグル内に限定。",
            "推測は根拠を添えて提示し、読者の安全を確保。",
        ]
    spoiler = data.get("spoiler") or {}
    foreshadowings = clean_list(spoiler.get("foreshadowings"))[:4]
    if not foreshadowings:
        foreshadowings = ["既知の伏線を整理中。", "新情報の真偽を確認中。"]
    predictions = clean_list(spoiler.get("predictions"))[:2]
    if not predictions:
        predictions = ["次号の公式情報待ち。", "確定情報が出次第更新予定。"]

    allowed_urls = {link.get("url") for link in official_links if link.get("url")}
    references: List[Dict[str, str]] = []
    for item in data.get("reference_links") or []:
        if not isinstance(item, dict):
            continue
        label = (item.get("label") or item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not label or not url:
            continue
        if allowed_urls and url not in allowed_urls:
            continue
        references.append({"label": label, "url": url})
    if not references:
        references = official_links[:3]

    glossary_updates = _clean_glossary_items(data.get("glossary_updates") or data.get("glossary") or [])

    return {
        "intro": (data.get("intro") or "").strip(),
        "summary_points": summary_points,
        "spoiler": {
            "synopsis": (spoiler.get("synopsis") or "").strip(),
            "foreshadowings": foreshadowings,
            "predictions": predictions,
        },
        "reference_links": references,
        "glossary_updates": glossary_updates,
    }


def _normalize_insight_payload(data: Dict[str, Any], official_links: List[Dict[str, str]]) -> Dict[str, Any]:
    def clean_str_list(value: Any) -> List[str]:
        result: List[str] = []
        if isinstance(value, list):
            for entry in value:
                if isinstance(entry, str):
                    text = entry.strip()
                    if text:
                        result.append(text)
        return result

    def clean_dict_list(value: Any, keys: Tuple[str, str]) -> List[Dict[str, str]]:
        cleaned: List[Dict[str, str]] = []
        if isinstance(value, list):
            for entry in value:
                if not isinstance(entry, dict):
                    continue
                first = (entry.get(keys[0]) or "").strip()
                second = (entry.get(keys[1]) or "").strip()
                if first and second:
                    cleaned.append({keys[0]: first, keys[1]: second})
        return cleaned

    allowed_urls = {link.get("url") for link in official_links if link.get("url")}
    references: List[Dict[str, str]] = []
    for item in data.get("reference_links") or []:
        if not isinstance(item, dict):
            continue
        label = (item.get("label") or item.get("title") or "").strip()
        url = (item.get("url") or "").strip()
        if not label or not url:
            continue
        if allowed_urls and url not in allowed_urls:
            continue
        references.append({"label": label, "url": url})
    if not references:
        references = official_links[:3]

    summary_points = clean_str_list(data.get("summary_points"))[:3]
    if not summary_points:
        summary_points = [
            "公開済みの設定やテーマをネタバレ無しで俯瞰。",
            "キャラクターの価値観を既出情報から読み解く。",
            "今日から実践できる小さな一歩を提示。",
        ]

    themes = clean_dict_list(data.get("themes"), ("title", "detail"))[:3]
    if not themes:
        themes = [
            {"title": "テーマ整理中", "detail": "最新の公開情報を確認次第更新します。"},
            {"title": "モチーフ整理中", "detail": "既出の設定集から構造化中です。"},
        ]

    characters = clean_dict_list(data.get("characters"), ("name", "focus"))[:3]
    if not characters:
        characters = [
            {"name": "主人公", "focus": "既出エピソードで見える価値観を整理。"},
            {"name": "主要キャラ", "focus": "テーマとの関連を確認中。"},
        ]

    actions = clean_str_list(data.get("actions"))[:3]
    if not actions:
        actions = [
            "気になるシーンを読み返して感情の動きをメモする。",
            "公式設定資料を引用して固有名詞の意味を確認する。",
            "日常の出来事に作品テーマを当てはめて考察してみる。",
        ]

    return {
        "intro": (data.get("intro") or "").strip(),
        "summary_points": summary_points,
        "themes": themes,
        "characters": characters,
        "reference_links": references,
    }


def generate_seo_title(series: Dict[str, Any], entry: Dict[str, Any], mode: str) -> str:
    series_name = series.get("name", "")
    chapter_label = entry.get("chapter") or entry.get("title") or "最新話"
    if mode == "spoiler":
        title = f"{series_name}｜{chapter_label}｜最新話ネタバレ・感想・考察"
    else:
        topic = entry.get("title") or entry.get("summary", "").split("。")[0]
        title = f"{series_name}｜{chapter_label}｜ネタバレ無し考察｜{topic}".strip("｜")
    return title[:60] if title else f"{series_name} {mode}"



def generate_article_sections(series: Dict[str, Any], entry: Dict[str, Any], mode: str) -> Optional[Dict[str, Any]]:
    if not OPENAI_API_KEY:
        return None

    official_links = series.get("official_links", [])
    official_text = "\n".join(
        f"- {link.get('label')} : {link.get('url')}" for link in official_links if link.get("label") and link.get("url")
    ) or "- （公式リンク情報なし。参考リンクがなければ空配列で返す）"
    fallback_title = generate_seo_title(series, entry, mode)

    if mode == "insight":
        user_prompt = ARTICLE_INSIGHT_USER_TMPL.substitute(
            series_name=series.get("name"),
            chapter=entry.get("chapter") or entry.get("title", "最新話"),
            entry_title=fallback_title,
            entry_summary=entry.get("summary", "")[:400],
            official_links=official_text,
        )
        insight_system = ARTICLE_SYSTEM_PROMPT_INSIGHT + ARTICLE_INSIGHT_SYSTEM_EXTRA
        raw = _call_openai(insight_system, user_prompt, temperature=0.5)
        json_str = _extract_json_block(raw)
        if not json_str:
            return None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            review_prompt = ARTICLE_INSIGHT_REVIEW_TMPL.format(raw=json_str)
            reviewed = _call_openai(ARTICLE_REVIEW_SYSTEM, review_prompt, temperature=0.2)
            json_str = _extract_json_block(reviewed)
            if not json_str:
                return None
            data = json.loads(json_str)
        payload = _normalize_insight_payload(data, official_links)
        payload["title"] = data.get("title") or fallback_title
        return payload

    user_prompt = ARTICLE_SPOILER_USER_TMPL.substitute(
        series_name=series.get("name"),
        chapter=entry.get("chapter") or entry.get("title", "最新話"),
        entry_title=fallback_title,
        entry_summary=entry.get("summary", "")[:400],
        official_links=official_text,
    )
    raw = _call_openai(ARTICLE_SYSTEM_PROMPT_SPOILER, user_prompt, temperature=0.55)
    json_str = _extract_json_block(raw)
    if not json_str:
        return None
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        review_prompt = ARTICLE_SPOILER_REVIEW_TMPL.format(raw=json_str)
        reviewed = _call_openai(ARTICLE_REVIEW_SYSTEM, review_prompt, temperature=0.2)
        json_str = _extract_json_block(reviewed)
        if not json_str:
            return None
        data = json.loads(json_str)
    payload = _normalize_spoiler_payload(data, official_links)
    payload["title"] = data.get("title") or fallback_title
    return payload


def load_glossary_terms(series_slug: str) -> List[Dict[str, str]]:
    path = GLOSSARY_DIR / f"{series_slug}.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("terms", [])


def save_glossary_terms(series_slug: str, terms: List[Dict[str, str]]) -> None:
    path = GLOSSARY_DIR / f"{series_slug}.yaml"
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump({"terms": terms}, f, allow_unicode=True, sort_keys=False)


def _clean_glossary_items(items: Any) -> List[Dict[str, str]]:
    cleaned = []
    if not isinstance(items, list):
        return cleaned
    for entry in items:
        if not isinstance(entry, dict):
            continue
        term = (entry.get("term") or "").strip()
        desc = (entry.get("description") or "").strip()
        if not term or not desc:
            continue
        cleaned.append(
            {
                "term": term,
                "reading": (entry.get("reading") or "").strip(),
                "description": desc,
                "reference": (entry.get("reference") or "").strip(),
            }
        )
    return cleaned


def ensure_glossary_terms(series: Dict[str, Any], desired: int = 30) -> List[Dict[str, str]]:
    """
    Ensure glossary has at least `desired` terms by generating missing entries via OpenAI.
    新しい用語を増やすことを目指すが、無意味なプレースホルダーは作らない。
    """
    terms = load_glossary_terms(series["slug"])

    def is_placeholder(term: str) -> bool:
        return "用語補完" in term or term.endswith("用語")

    terms = [t for t in terms if not is_placeholder(t.get("term", ""))]
    target = max(desired, len(terms) + 3)

    new_items: List[Dict[str, str]] = []
    if OPENAI_API_KEY:
        official_links = series.get("official_links") or []
        link_text = "\n".join(f"- {link.get('label')}: {link.get('url')}" for link in official_links[:3])
        prompt = [
            f"シリーズ名: {series.get('name')}",
            f"タグ: {', '.join(series.get('tags', []))}",
            f"既存用語数: {len(terms)}",
            "参考リンク:",
            link_text or "- (なし)",
            f"残り{target - len(terms)}件を追加してください。用語は初見でもわかる40〜80文字の説明を。"
        ]
        user_prompt = "\n".join(prompt)
        raw = _call_openai(GLOSSARY_SYSTEM_PROMPT, user_prompt, temperature=0.55)
        try:
            new_items = _clean_glossary_items(json.loads(raw)) if raw else []
        except json.JSONDecodeError:
            new_items = []

    seen = {t["term"] for t in terms}
    for item in new_items:
        if item["term"] not in seen:
            terms.append(item)
            seen.add(item["term"])
        if len(terms) >= target:
            break

    save_glossary_terms(series["slug"], terms)
    return terms

    official_links = series.get("official_links") or []
    link_text = "\n".join(f"- {link.get('label')}: {link.get('url')}" for link in official_links[:3])
    prompt = [
        f"シリーズ名: {series.get('name')}",
        f"タグ: {', '.join(series.get('tags', []))}",
        f"既存用語数: {len(terms)}",
        "公式リンク:",
        link_text or "- (なし)",
        f"あと{desired - len(terms)}語追加してください。重複は避けてください。",
    ]
    user_prompt = "\n".join(prompt)
    raw = _call_openai(GLOSSARY_SYSTEM_PROMPT, user_prompt, temperature=0.55)
    try:
        new_items = _clean_glossary_items(json.loads(raw)) if raw else []
    except json.JSONDecodeError:
        new_items = []
    seen = {t["term"] for t in terms}
    for item in new_items:
        if item["term"] not in seen:
            terms.append(item)
            seen.add(item["term"])
        if len(terms) >= desired:
            break
    if len(terms) < desired:
        missing = desired - len(terms)
        for idx in range(missing):
            placeholder = f"{series['name']}用語補完{idx+1}"
            if placeholder in seen:
                continue
            terms.append(
                {
                    "term": placeholder,
                    "reading": "",
                    "description": "公式情報に基づく用語の補完。詳細は次回更新で追記予定。",
                    "reference": "自動補完",
                }
            )
            seen.add(placeholder)
    save_glossary_terms(series["slug"], terms)
    return terms


def select_glossary_terms(series_slug: str, terms: List[Dict[str, str]], state: Dict[str, Any]) -> Tuple[List[Dict[str, str]], int]:
    """
    Show all available glossary terms. We no longer stage terms gradually so
    readers can see the full list and増加を確認できるようにする。
    """
    state.setdefault("glossary_progress", {})[series_slug] = len(terms)
    return terms, 0


def _merge_reference_links(
    primary: Optional[List[Dict[str, str]]], fallback: Optional[List[Dict[str, str]]]
) -> List[Dict[str, str]]:
    merged: List[Dict[str, str]] = []
    seen: set[str] = set()
    for block in (primary or [], fallback or []):
        for link in block or []:
            if not link:
                continue
            url = (link.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            label = link.get("label") or url
            merged.append({"label": label, "url": url})
    return merged


def build_spoiler_context(
    series: Dict[str, Any],
    entry: Dict[str, Any],
    ogp_path: Optional[str],
    draft: bool,
    payload: Optional[Dict[str, Any]],
    hero_image: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    chapter_label = entry.get("chapter", entry.get("title", "最新話")) or "最新話"
    summary = payload.get("summary_points") if payload else default_summary_points(series["name"], entry.get("chapter", ""))
    spoiler_block = payload.get("spoiler") if payload else {
        "synopsis": entry.get("summary", "")[:120],
        "foreshadowings": ["伏線の整理を準備中。", "次の謎はここから。"],
        "predictions": ["次回の展開を予想。", "伏線が動きそうなポイント。"],
    }
    glossary_updates = payload.get("glossary_updates") if payload else []
    if not glossary_updates:
        existing_terms = ensure_glossary_terms(series, desired=30)
        recent = existing_terms[-3:] if existing_terms else []
        glossary_updates = [
            {
                "term": term.get("term", ""),
                "reading": term.get("reading", ""),
                "description": term.get("description", ""),
            }
            for term in recent
        ]
    payload_links = payload.get("reference_links") if payload else []
    supplemental_links = entry.get("research_links") or series.get("official_links", [])
    reference_links = _merge_reference_links(payload_links, supplemental_links)

    official_links = series.get("official_links", [])
    official_link = official_links[0] if official_links else None
    affiliates = build_affiliate_urls(series)
    others = prioritized_other_affiliates(series)
    disclaimer_text = series.get("defaults", {}).get(
        "disclaimer",
        "公開情報のみを基にし、ネタバレは折りたたみ内に収めています。",
    )

    return {
        "title": (payload.get("title") if payload else entry.get("title", f"{series['name']} 最新話考察")),
        "series": series["name"],
        "chapter": entry.get("chapter", entry.get("title", "最新話")),
        "chapter_label": chapter_label,
        "date": entry.get("date"),
        "tags": series.get("tags", []),
        "draft": draft,
        "affiliate_ids": {
            "amazon": affiliates["amazon"],
            "rakuten": affiliates["rakuten"],
            "others": others,
        },
        "affiliate_widgets": {
            "amazon": affiliates["amazon"],
            "rakuten": affiliates["rakuten"],
        },
        "disclaimer": disclaimer_text,
        "images": [ogp_path] if ogp_path else [],
        "intro": payload.get("intro") if payload else entry.get(
            "intro",
            f"{series['name']}の最新話をさっくり整理します。ネタバレはトグル内に収めています。",
        ),
        "summary_points": summary[:3],
        "spoiler": spoiler_block,
        "glossary_updates": glossary_updates,
        "reference_links": reference_links,
        "hero_image": hero_image,
        "official_link": official_link,
        "spoiler_notice": "本記事は最新話までのネタバレを含みます。",
    }


def build_insight_context(
    series: Dict[str, Any],
    entry: Dict[str, Any],
    ogp_path: Optional[str],
    draft: bool,
    payload: Optional[Dict[str, Any]],
    hero_image: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    official_links = series.get("official_links", [])
    official_link = official_links[0] if official_links else None
    affiliates = build_affiliate_urls(series)
    others = prioritized_other_affiliates(series)
    disclaimer_text = series.get("defaults", {}).get(
        "disclaimer",
        "公式情報のみを参照し、ネタバレは折りたたみ領域に限定します。",
    )

    summary = payload.get("summary_points") if payload else [
        f"{series['name']}の世界観とテーマをネタバレ無しで整理します。",
        "既出情報をもとにキャラクターの感情と決断を読み解きます。",
        "伏線とモチーフの因果を丁寧に言語化します。",
    ]

    insight_block = payload if payload else {
        "themes": [
            {"title": "テーマ整理中", "detail": "最新話情報を基に整理準備中。"},
            {"title": "モチーフ整理中", "detail": "公開情報の確認後に解説します。"},
        ],
        "characters": [
            {"name": "主要キャラA", "focus": "行動原理と葛藤の接点を既出設定から確認中。"},
            {"name": "主要キャラB", "focus": "価値観と作品テーマの結びつきを整理中。"},
        ],
        "reference_links": series.get("official_links", []),
    }

    reference_links = insight_block.get("reference_links", series.get("official_links", []))

    return {
        "title": (payload.get("title") if payload else f"{entry.get('title', series['name'])} 考察メモ（ネタバレ無し）"),
        "series": series["name"],
        "chapter": entry.get("chapter", entry.get("title", "最新話")),
        "date": entry.get("date"),
        "tags": list({*series.get("tags", []), "ネタバレ無し"}),
        "draft": draft,
        "affiliate_ids": {
            "amazon": affiliates["amazon"],
            "rakuten": affiliates["rakuten"],
            "others": others,
        },
        "affiliate_widgets": {
            "amazon": affiliates["amazon"],
            "rakuten": affiliates["rakuten"],
        },
        "disclaimer": disclaimer_text,
        "images": [ogp_path] if ogp_path else [],
        "intro": insight_block.get("intro") or entry.get(
            "intro",
            f"{series['name']}の公開済み情報だけを使って考察を深めます。",
        ),
        "summary_points": summary[:3],
        "insight": {
            "themes": insight_block.get("themes", []),
            "characters": insight_block.get("characters", []),
        },
        "reference_links": reference_links,
        "hero_image": hero_image,
        "official_link": official_link,
    }


def build_glossary_context(series: Dict[str, Any], terms: List[Dict[str, str]], remaining_count: int) -> Dict[str, Any]:
    affiliates = build_affiliate_urls(series)
    official_links = series.get("official_links", [])
    official_link = official_links[0] if official_links else None
    disclaimer_text = series.get("defaults", {}).get(
        "disclaimer",
        "公式情報のみを参照し、ネタバレは折りたたみ内に限定しています。",
    )
    intro = (
        f"{series['name']}に登場する用語・組織・人物を公式情報から抜粋し、"
        "初見読者でも追いやすいように整理しました。"
    )
    glossary_note = None
    if remaining_count > 0:
        glossary_note = f"※ さらに {remaining_count} 件の用語を順次追加予定です。"
    return {
        "title": f"{series['name']} 用語集",
        "series": series["name"],
        "series_slug": series["slug"],
        "tags": list({*series.get("tags", []), "用語解説"}),
        "disclaimer": disclaimer_text,
        "affiliate_ids": {
            "amazon": affiliates["amazon"],
            "rakuten": affiliates["rakuten"],
            "others": [],
        },
        "affiliate_widgets": {
            "amazon": affiliates["amazon"],
            "rakuten": affiliates["rakuten"],
        },
        "intro": intro,
        "glossary": terms,
        "glossary_note": glossary_note,
        "official_link": official_link,
    }


def load_backlog_entries(series_slug: str) -> List[Dict[str, Any]]:
    path = BACKLOG_DIR / f"{series_slug}.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = data.get("entries") or data.get("topics") or []
    return [entry for entry in entries if isinstance(entry, dict)]


def _chapter_number_hint(entry: Dict[str, Any]) -> Optional[int]:
    """
    Try to extract a chapter number from common fields so we can post from 1話 onward.
    Falls back to None if no usable number is found.
    """
    for key in ("chapter_number", "chapter", "title"):
        value = entry.get(key)
        if value is None:
            continue
        # Accept both ints and strings with digits like "第3話"
        if isinstance(value, int):
            return value
        match = re.search(r"\d+", str(value))
        if match:
            try:
                return int(match.group())
            except ValueError:
                continue
    return None


def sort_backlog_entries(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Sort backlog to start from the earliest chapter we can infer, keeping original
    order as a tiebreaker so author-provided ordering is preserved when no numbers.
    """
    with_index = list(enumerate(entries))

    def sort_key(item: Tuple[int, Dict[str, Any]]) -> Tuple[int, int]:
        idx, entry = item
        num = _chapter_number_hint(entry)
        # If no number, place after numbered items but keep original order.
        return (num if num is not None else 10_000_000, idx)

    return [entry for _, entry in sorted(with_index, key=sort_key)]


def select_backlog_entry(series: Dict[str, Any], state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    backlog_entries = sort_backlog_entries(load_backlog_entries(series["slug"]))
    if not backlog_entries:
        return None
    progress = state.setdefault("backlog_progress", {})
    index = progress.get(series["slug"], 0)
    if index >= len(backlog_entries):
        return None
    entry = backlog_entries[index]
    progress[series["slug"]] = index + 1
    official_links = series.get("official_links", [])
    default_link = official_links[0].get("url") if official_links and official_links[0].get("url") else ""
    research_links = entry.get("research_links") or []
    return {
        "id": entry.get("id") or f"{series['slug']}-backlog-{index}",
        "title": entry.get("title", f"{series['name']} バックログ考察"),
        "link": entry.get("link") or default_link or "",
        "summary": entry.get("summary", ""),
        "chapter": entry.get("chapter", entry.get("title", "")),
        "intro": entry.get("intro", entry.get("summary", "")[:140]),
        "date": entry.get("date") or dt.datetime.now(dt.timezone.utc).isoformat(),
        "force_modes": entry.get("force_modes"),
        "research_links": research_links,
        "is_backlog": True,
    }


def collect_manual_entry(series: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    release_day = series.get("release_day")
    if not release_day:
        return None
    try:
        release_date = dt.date.fromisoformat(release_day)
    except ValueError:
        return None
    if release_date != dt.date.today():
        return None
    title = f"{series['name']} {release_date.strftime('%Y/%m/%d')} 発売速報"
    return {
        "id": f"{series['slug']}-{release_day}",
        "title": title,
        "link": series.get("official_links", [{}])[0].get("url", ""),
        "summary": "公式発売日を待ちながら、既知の伏線を整理した暫定版ドラフトです。",
        "chapter": "最新号速報",
        "intro": "発売日速報のため本文はドラフト扱いです。公式配信後に更新されます。",
        "date": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def map_feed_entry(series: Dict[str, Any], entry: feedparser.FeedParserDict) -> Dict[str, Any]:
    published = entry.get("published_parsed")
    date_iso = (
        dt.datetime(*published[:6], tzinfo=dt.timezone.utc).isoformat()
        if published
        else dt.datetime.now(dt.timezone.utc).isoformat()
    )
    return {
        "id": entry.get("id") or entry.get("link") or entry.get("title", ""),
        "title": entry.get("title", f"{series['name']} 最新話"),
        "link": entry.get("link", ""),
        "summary": entry.get("summary", ""),
        "chapter": entry.get("title", ""),
        "intro": entry.get("summary", "")[:140],
        "date": date_iso,
    }


def load_entries_for_series(series: Dict[str, Any], state: Dict[str, Any]) -> List[Dict[str, Any]]:
    if series.get("manual"):
        manual_entry = collect_manual_entry(series)
        if manual_entry:
            return [manual_entry]
        fallback_manual = build_fallback_entry(series)
        return [fallback_manual] if fallback_manual else []
    entries = []
    for entry in fetch_feed(series.get("rss", "")):
        entries.append(map_feed_entry(series, entry))
    if not entries:
        backlog_entry = select_backlog_entry(series, state)
        if backlog_entry:
            entries.append(backlog_entry)
    if not entries:
        fallback = build_fallback_entry(series)
        if fallback:
            entries.append(fallback)
    if not entries:
        suggest = build_suggest_entry(series)
        if suggest:
            entries.append(suggest)
    return entries


def build_fallback_entry(series: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    topics = series.get("fallback_topics") or []
    if not topics:
        return None
    today = dt.date.today()
    index = today.toordinal() % len(topics)
    topic = topics[index]
    topic_slug = slugify(topic)
    official_links = series.get("official_links") or [{}]
    primary_link = official_links[0] if isinstance(official_links, list) and official_links else {}
    return {
        "id": f"{series['slug']}-fallback-{today.isoformat()}-{topic_slug}",
        "title": topic,
        "link": primary_link.get("url", ""),
        "summary": topic,
        "chapter": topic,
        "intro": f"{series['name']}の既出情報をもとに「{topic}」を深掘りします（ネタバレ無し）。",
        "date": dt.datetime.now(dt.timezone.utc).isoformat(),
        "force_modes": ["spoiler"],
        "is_fallback": True,
    }


def fetch_google_suggestions(query: str) -> List[str]:
    """
    Fetch Google suggest keywords (Firefox client endpoint).
    Returns a list of suggestion strings; network errors are swallowed to keep generation moving.
    """
    try:
        resp = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "hl": "ja", "q": query},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and len(data) >= 2 and isinstance(data[1], list):
            return [s for s in data[1] if isinstance(s, str)]
    except Exception:
        return []
    return []


def build_suggest_entry(series: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Build a fallback entry using Googleサジェストをベースにしたキーワードでの考察記事。
    生成内容が推測に寄るため、安全側で insight モードに限定する。
    """
    base_query = f"{series.get('name','')} 最新話 考察"
    suggestions = fetch_google_suggestions(base_query)
    if not suggestions:
        suggestions = fetch_google_suggestions(series.get("name", ""))
    if not suggestions:
        return None
    topic = suggestions[0]
    topic_slug = slugify(topic)
    official_links = series.get("official_links") or [{}]
    primary_link = official_links[0] if isinstance(official_links, list) and official_links else {}
    now = dt.datetime.now(dt.timezone.utc)
    return {
        "id": f"{series['slug']}-suggest-{now.strftime('%Y%m%d')}-{topic_slug}",
        "title": topic,
        "link": primary_link.get("url", ""),
        "summary": topic,
        "chapter": topic,
        "intro": f"{series['name']}の話題キーワード「{topic}」をもとにネタバレなしで整理します。",
        "date": now.isoformat(),
        "force_modes": ["spoiler"],
        "is_fallback": True,
    }


def write_markdown_file(path: Path, content: str) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as f:
        f.write(content)


# ASCII override prompts (avoid mojibake)
ARTICLE_SYSTEM_PROMPT_SPOILER = """
You are a Japanese manga spoiler writer. Always cover the latest chapter first; if unavailable, start from chapter 1 in order.
Write detailed chronological spoilers with key events, quotes, character feelings, foreshadowings (3-4), and predictions (2-3 with reasoning).
Keep Japanese output natural. Add 1-3 glossary items (new terms preferred; otherwise enrich existing).
"""

ARTICLE_SYSTEM_PROMPT_INSIGHT = (
    "You are a spoiler-free analysis writer in Japanese. "
    "Avoid core spoilers, highlight themes and character motives with concrete examples. "
    "Keep the tone friendly and curious so readers want the next chapter."
)

ARTICLE_REVIEW_SYSTEM = (
    "You are a QA checker. Validate the given JSON, fix omissions, and return only corrected JSON."
)

ARTICLE_SPOILER_REVIEW_TMPL = """Validate and fix this JSON for a blog spoiler. If synopsis < 1500 chars, extend it. Return only JSON.

{raw}

"""
ARTICLE_INSIGHT_REVIEW_TMPL = """Validate and fix this JSON for a spoiler-free analysis. Return only corrected JSON.

{raw}
"""

ARTICLE_INSIGHT_SYSTEM_EXTRA = (
    "Keep output concise and readable. Add concrete examples and reasons, not just abstractions. "
    "Leave a bit of curiosity so readers want the next chapter."
)

GLOSSARY_SYSTEM_PROMPT = (
    "Create a manga glossary in Japanese. Add 1-3 terms (skills/places/organizations) relevant to this article. "
    "40-80 chars per item. Return JSON: {"term":"...","reading":"...","description":"...","reference":"..."}"
)
