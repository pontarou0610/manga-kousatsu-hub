from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import feedparser
import frontmatter
import openai
import requests
import yaml
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
CONTENT_DIR = ROOT_DIR / "content"
TEMPLATE_DIR = ROOT_DIR / "templates"
STATIC_DIR = ROOT_DIR / "static"
OGP_DIR = STATIC_DIR / "ogp"
GLOSSARY_DIR = DATA_DIR / "glossary"

OGP_WIDTH = 1200
OGP_HEIGHT = 630
OGP_BG = "#090a13"
OGP_ACCENT = "#ff5c7b"

load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
PEXELS_API_ENDPOINT = "https://api.pexels.com/v1/search"
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

ARTICLE_SYSTEM_PROMPT_SPOILER = (
    "あなたは人気漫画の考察ブログを運営する日本語編集者です。"
    "公式情報のみを扱い、ネタバレは指定されたトグル内に限定し、"
    "事実確認できない内容は推測として明確に示してください。"
)
ARTICLE_SYSTEM_PROMPT_INSIGHT = (
    "あなたは人気漫画の設定・テーマを整理する日本語編集者です。"
    "作品の公開済み情報だけを使い、ネタバレは避けて解説してください。"
    "読者が次の行動を取れるよう、具体的な視点と小さな一歩を提示します。"
)
ARTICLE_REVIEW_SYSTEM = (
    "あなたは厳格な校閲者です。渡されたJSONを仕様に合わせて整形し、"
    "欠落データを補完したうえで有効なJSONだけを返してください。"
)
ARTICLE_SPOILER_USER_TMPL = """\
以下の情報を使って、漫画考察記事向けの要約データをJSONで作成してください。

# シリーズ情報
- シリーズ名: {series_name}
- 最新話/章: {chapter}
- エントリタイトル: {entry_title}
- RSS概要: {entry_summary}
- 利用可能な公式リンク（最大3件まで利用可）:
{official_links}

# 出力フォーマット
JSONのキーは `intro`, `summary_points`, `spoiler`, `reference_links` の4つ。
1. `intro`: 80〜140字、ネタバレ無し。
2. `summary_points`: 3項目、箇条書きテキスト（ネタバレ無し）。
3. `spoiler`: { "synopsis": 120字以内, "foreshadowings": 2項目, "predictions": 2項目 }。ここだけネタバレ可。推測は根拠を添える。
4. `reference_links`: 提供リスト内の公式リンクのみ使用。要素は { "label": "...", "url": "..." }。

JSON以外の文字は一切出力しない。
"""
ARTICLE_SPOILER_REVIEW_TMPL = """\
次のJSONをブログ仕様に整えてください。欠落項目は補完し、形式違反は修正してください。

{raw}
"""
ARTICLE_INSIGHT_USER_TMPL = """\
以下の情報を使って、ネタバレ無しの分析記事用JSONを作成してください。

# シリーズ情報
- シリーズ名: {series_name}
- 最新話/章: {chapter}
- エントリタイトル: {entry_title}
- RSS概要: {entry_summary}
- 利用可能な公式リンク（最大3件まで利用可）:
{official_links}

# 出力フォーマット
キーは `intro`, `summary_points`, `themes`, `characters`, `actions`, `reference_links`。
1. `intro`: 80〜140字でネタバレ無しの導入。
2. `summary_points`: 3項目、箇条書きテキスト（ネタバレ禁止）。
3. `themes`: 2項目、各 { "title": "...", "detail": "..." } としてテーマを解説。
4. `characters`: 2項目、各 { "name": "...", "focus": "..." } としてキャラクター視点を整理。
5. `actions`: 2〜3項目、読者が今日試せる小さな行動。
6. `reference_links`: 提供リスト内の公式リンクのみ使用。要素は { "label": "...", "url": "..." }。

JSON以外の文字は出力しないでください。
"""
ARTICLE_INSIGHT_REVIEW_TMPL = """\
次のJSONをネタバレ無し分析記事の仕様に整えてください。欠落項目を補完し、形式違反を修正してください。

{raw}
"""


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_series_config(path: Path = DATA_DIR / "series.yaml") -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"series設定ファイルが見つかりません: {path}")
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def load_state(path: Path = DATA_DIR / "state.json") -> Dict[str, Any]:
    if not path.exists():
        return {"entries": []}
    with path.open(encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"entries": []}


def save_state(state: Dict[str, Any], path: Path = DATA_DIR / "state.json") -> None:
    with path.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def slugify(value: str) -> str:
    value = value.lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"[\s_-]+", "-", value).strip("-")
    return value or "post"


def hash_entry(*parts: str) -> str:
    joined = "::".join(parts)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()


def fetch_feed(url: str) -> Iterable[feedparser.FeedParserDict]:
    if not url:
        return []
    headers = {
        "User-Agent": "manga-kousatsu-hub-bot (+https://github.com/<GitHubユーザー名>/manga-kousatsu-hub)",
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

    def draw_text(text: str, xy: Tuple[int, int], font, max_width: int, line_height: int) -> None:
        words = text.split()
        line = ""
        x, y = xy
        for word in words:
            test_line = (line + " " + word).strip()
            w, _ = draw.textsize(test_line, font=font)
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
    return f"/{rel_path}"


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
    amazon_url = f"https://www.amazon.co.jp/dp/{amazon_asin}?tag=YOUR_AMAZON_TAG" if amazon_asin else ""
    rakuten_url = f"https://hb.afl.rakuten.co.jp/?{rakuten_params}" if rakuten_params else ""
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
    except Exception:
        return None


def _extract_json_block(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        return match.group(0)
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
    spoiler = data.get("spoiler") or {}
    foreshadowings = clean_list(spoiler.get("foreshadowings"))[:2]
    predictions = clean_list(spoiler.get("predictions"))[:2]

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

    return {
        "intro": (data.get("intro") or "").strip(),
        "summary_points": summary_points,
        "spoiler": {
            "synopsis": (spoiler.get("synopsis") or "").strip(),
            "foreshadowings": foreshadowings,
            "predictions": predictions,
        },
        "reference_links": references,
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

    return {
        "intro": (data.get("intro") or "").strip(),
        "summary_points": clean_str_list(data.get("summary_points"))[:3],
        "themes": clean_dict_list(data.get("themes"), ("title", "detail"))[:2],
        "characters": clean_dict_list(data.get("characters"), ("name", "focus"))[:2],
        "actions": clean_str_list(data.get("actions"))[:3],
        "reference_links": references,
    }


def generate_article_sections(series: Dict[str, Any], entry: Dict[str, Any], mode: str) -> Optional[Dict[str, Any]]:
    if not OPENAI_API_KEY:
        return None

    official_links = series.get("official_links", [])
    official_text = "\n".join(
        f"- {link.get('label')} : {link.get('url')}" for link in official_links if link.get("label") and link.get("url")
    ) or "- （公式リンク情報なし。参考リンクがなければ空配列で返す）"

    if mode == "insight":
        user_prompt = ARTICLE_INSIGHT_USER_TMPL.format(
            series_name=series.get("name"),
            chapter=entry.get("chapter") or entry.get("title", "最新話"),
            entry_title=entry.get("title", ""),
            entry_summary=entry.get("summary", "")[:400],
            official_links=official_text,
        )
        raw = _call_openai(ARTICLE_SYSTEM_PROMPT_INSIGHT, user_prompt, temperature=0.5)
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
        return _normalize_insight_payload(data, official_links)

    user_prompt = ARTICLE_SPOILER_USER_TMPL.format(
        series_name=series.get("name"),
        chapter=entry.get("chapter") or entry.get("title", "最新話"),
        entry_title=entry.get("title", ""),
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
    return _normalize_spoiler_payload(data, official_links)


def load_glossary_terms(series_slug: str) -> List[Dict[str, str]]:
    path = GLOSSARY_DIR / f"{series_slug}.yaml"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("terms", [])


def build_spoiler_context(
    series: Dict[str, Any],
    entry: Dict[str, Any],
    ogp_path: Optional[str],
    draft: bool,
    payload: Optional[Dict[str, Any]],
    hero_image: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    summary = payload.get("summary_points") if payload else default_summary_points(series["name"], entry.get("chapter", ""))
    spoiler_block = payload.get("spoiler") if payload else {
        "synopsis": entry.get("summary", "")[:120],
        "foreshadowings": ["伏線整理中。", "続報を確認中。"],
        "predictions": ["公式情報待ち。", "確定情報が出次第更新予定。"],
    }
    reference_links = payload.get("reference_links") if payload else series.get("official_links", [])

    affiliates = build_affiliate_urls(series)
    others = prioritized_other_affiliates(series)
    disclaimer_text = series.get("defaults", {}).get(
        "disclaimer",
        "公式情報のみを参照し、ネタバレは折りたたみ内に限定しています。",
    )

    return {
        "title": entry.get("title", f"{series['name']} 最新考察"),
        "series": series["name"],
        "chapter": entry.get("chapter", entry.get("title", "最新話")),
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
            f"{series['name']}の最新話を公式情報のみで整理。ネタバレはトグル内に限定しています。",
        ),
        "summary_points": summary[:3],
        "spoiler": spoiler_block,
        "reference_links": reference_links,
        "hero_image": hero_image,
    }


def build_insight_context(
    series: Dict[str, Any],
    entry: Dict[str, Any],
    ogp_path: Optional[str],
    draft: bool,
    payload: Optional[Dict[str, Any]],
    hero_image: Optional[Dict[str, str]],
) -> Dict[str, Any]:
    affiliates = build_affiliate_urls(series)
    others = prioritized_other_affiliates(series)
    disclaimer_text = series.get("defaults", {}).get(
        "disclaimer",
        "公式情報のみを参照し、ネタバレは折りたたみ内に限定しています。",
    )

    summary = payload.get("summary_points") if payload else [
        f"{series['name']}の世界観やテーマをネタバレ無しで整理。",
        "キャラクターの心理・価値観を既出情報だけで読み解く。",
        "次回に向けた着眼点を行動ベースで提示。",
    ]

    insight_block = payload if payload else {
        "themes": [
            {"title": "テーマ整理中", "detail": "最新話情報を基に整理準備中。"},
            {"title": "モチーフ整理中", "detail": "公開情報の確認後に解説します。"},
        ],
        "characters": [
            {"name": "主要キャラA", "focus": "行動原理を既出設定から考察中。"},
            {"name": "主要キャラB", "focus": "価値観と作品テーマの関係を確認中。"},
        ],
        "actions": [
            "気になるシーンをもう一度読み直し、感情の変化に注目する。",
            "公式設定資料で固有名詞の使い方を確認する。",
        ],
        "reference_links": series.get("official_links", []),
    }

    return {
        "title": f"{entry.get('title', series['name'])} 考察メモ（ネタバレ無し）",
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
            f"{series['name']}の公開済み情報をもとに、今読むべき視点を整理します。",
        ),
        "summary_points": summary[:3],
        "insight": {
            "themes": insight_block.get("themes", []),
            "characters": insight_block.get("characters", []),
            "actions": insight_block.get("actions", []),
        },
        "reference_links": insight_block.get("reference_links", series.get("official_links", [])),
        "hero_image": hero_image,
    }


def build_glossary_context(series: Dict[str, Any], terms: List[Dict[str, str]]) -> Dict[str, Any]:
    affiliates = build_affiliate_urls(series)
    disclaimer_text = series.get("defaults", {}).get(
        "disclaimer",
        "公式情報のみを参照し、ネタバレは折りたたみ内に限定しています。",
    )
    intro = (
        f"{series['name']}に登場する用語・組織・人物を公式情報から抜粋し、"
        "初見読者でも追いやすいように整理しました。"
    )
    return {
        "title": f"{series['name']} 用語集",
        "series": series["name"],
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


def load_entries_for_series(series: Dict[str, Any]) -> List[Dict[str, Any]]:
    if series.get("manual"):
        manual_entry = collect_manual_entry(series)
        return [manual_entry] if manual_entry else []
    entries = []
    for entry in fetch_feed(series.get("rss", "")):
        entries.append(map_feed_entry(series, entry))
    if not entries:
        fallback = build_fallback_entry(series)
        if fallback:
            entries.append(fallback)
    return entries


def build_fallback_entry(series: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    topics = series.get("fallback_topics") or []
    if not topics:
        return None
    today = dt.date.today()
    index = today.toordinal() % len(topics)
    topic = topics[index]
    topic_slug = slugify(topic)
    return {
        "id": f"{series['slug']}-fallback-{today.isoformat()}-{topic_slug}",
        "title": topic,
        "link": series.get("official_links", [{}])[0].get("url", ""),
        "summary": topic,
        "chapter": topic,
        "intro": f"{series['name']}の既出情報をもとに「{topic}」を深掘りします（ネタバレ無し）。",
        "date": dt.datetime.now(dt.timezone.utc).isoformat(),
        "force_modes": ["insight"],
        "is_fallback": True,
    }


def write_markdown_file(path: Path, content: str) -> None:
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as f:
        f.write(content)
