#!/usr/bin/env python3
"""
Main script for generating manga analysis posts.
Reads RSS feeds, generates content using OpenAI, and creates Hugo markdown files.
"""

import os
import json
import yaml
import feedparser
import frontmatter
from datetime import datetime
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
GENERATE_FALLBACK_TOPICS = os.getenv("GENERATE_FALLBACK_TOPICS", "true").strip().lower() not in (
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
    """Load backlog topics for a series."""
    backlog_file = BACKLOG_DIR / f"{series_slug}.yaml"
    if backlog_file.exists():
        with open(backlog_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data.get('topics', [])
    return []


def generate_spoiler_content(series: Dict[str, Any], chapter: str) -> Optional[Dict[str, Any]]:
    """Generate spoiler content using OpenAI."""
    system_prompt = f"""あなたは「{series['name']}」の考察記事を書く専門家です。
{series.get('defaults', {}).get('tone', '落ち着いた敬体で、根拠を示しつつ丁寧にまとめる。')}
{series.get('defaults', {}).get('prohibited', '誹謗中傷や憶測だけの断定、暴力的・過激な表現は避ける。')}

【重要な文章作成ルール】
- 句点（。）の後は必ず改行してください
- 1文を短く簡潔にまとめ、読みやすさを最優先してください
- 長い文章は避け、適切な長さで区切ってください"""

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

※すべてのテキストフィールドで、句点（。）の後は必ず改行（\n）を入れてください。"""

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
    
    # Get progress
    progress = state['glossary_progress'].get(series_slug, 0)
    
    # Publish terms incrementally (3 at a time)
    terms_to_publish = glossary_terms[:progress + 3]
    
    if len(terms_to_publish) == progress:
        print(f">> All glossary terms already published for {series['name']}")
        return
    
    # Prepare context
    context = {
        'title': f"{series['name']} 用語集",
        'date': datetime.now().strftime('%Y-%m-%dT%H:%M:%S+09:00'),
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
    
    # Output path
    output_dir = CONTENT_DIR / series_slug / "glossary"
    output_path = output_dir / "index.md"
    
    # Create post
    if create_post_from_template('post_glossary.md.j2', context, output_path):
        state['glossary_progress'][series_slug] = len(terms_to_publish)
        print(f"[OK] Updated glossary: {len(terms_to_publish)} terms")


def process_series(series: Dict[str, Any], state: Dict[str, Any]) -> None:
    """Process a single series: check RSS, generate posts."""
    print(f"\n>> Processing: {series['name']}")
    
    # Generate glossary if enabled
    if 'glossary' in series.get('content_modes', []):
        generate_glossary_post(series, state)
    
    # Check RSS feed
    if series.get('rss'):
        feed = feedparser.parse(series['rss'])
        
        for entry in feed.entries[:RSS_MAX_ENTRIES]:  # Throttle per run
            entry_hash = generate_hash(entry.link + entry.title)
            
            if entry_hash in state['entries']:
                continue
            
            print(f"[NEW] New entry: {entry.title}")
            
            # Generate spoiler post if enabled
            if 'spoiler' in series.get('content_modes', []):
                content = generate_spoiler_content(series, entry.title)
                if content:
                    # TODO: Create spoiler post
                    pass
            
            # Generate insight post if enabled
            if 'insight' in series.get('content_modes', []):
                content = generate_insight_content(series, entry.title)
                if content:
                    # TODO: Create insight post
                    pass
            
            # Mark as processed
            state['entries'].append(entry_hash)
    
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


def main():
    """Main execution function."""
    print(">> Starting post generation...")
    
    # Load configuration and state
    series_list = load_series_config()
    state = load_state()
    
    # Process each series
    for series in series_list:
        if series.get('manual', False):
            print(f">> Skipping manual series: {series['name']}")
            continue
        
        try:
            process_series(series, state)
        except Exception as e:
            print(f"[ERROR] Error processing {series['name']}: {e}")
            continue
    
    # Save state
    save_state(state)
    print("\n>> Post generation complete!")


if __name__ == "__main__":
    main()
