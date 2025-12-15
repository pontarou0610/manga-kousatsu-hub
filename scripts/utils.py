#!/usr/bin/env python3
"""
Utility functions for manga-kousatsu-hub post generation.
Handles OpenAI API calls, Pexels image fetching, and OGP image generation.
"""

import os
import json
import hashlib
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List

from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")  # backward compatible (single model)
OPENAI_MODEL_CANDIDATES = os.getenv("OPENAI_MODEL_CANDIDATES")  # preferred list (CSV)
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
AMAZON_TAG = os.getenv("AMAZON_TAG", "")

# Font path for OGP generation
FONT_PATH = Path("assets/fonts/NotoSansJP-Regular.ttf")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def _get_openai_model_candidates() -> List[str]:
    """
    Return an ordered list of model ids to try.

    Priority:
      1) OPENAI_MODEL_CANDIDATES (comma-separated)
      2) OPENAI_MODEL (single, backward compatible)
      3) default: try gpt-5.1 first, then gpt-4.1
    """
    if OPENAI_MODEL_CANDIDATES:
        return [m.strip() for m in OPENAI_MODEL_CANDIDATES.split(",") if m.strip()]
    if OPENAI_MODEL:
        return [OPENAI_MODEL.strip()]
    return ["gpt-5.1", "gpt-4.1"]


def _should_fallback_model(exc: Exception) -> bool:
    """
    Best-effort detection for model availability errors across openai-python versions.
    """
    msg = str(exc).lower()
    if "model" in msg and ("not found" in msg or "does not exist" in msg or "no such model" in msg):
        return True
    if "model" in msg and ("not supported" in msg or "unsupported" in msg):
        return True
    if "endpoint" in msg and ("not supported" in msg or "unsupported" in msg):
        return True
    status = getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)
    if status in (400, 404):
        return True
    code = getattr(exc, "code", None)
    if code is None:
        err = getattr(exc, "error", None)
        code = getattr(err, "code", None) if err is not None else None
    if isinstance(code, str) and code.lower() in ("model_not_found", "invalid_model"):
        return True
    return False


def generate_content_with_openai(
    prompt: str,
    system_prompt: str = "あなたは漫画考察記事を書く専門家です。",
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate content using OpenAI API.

    Args:
        prompt: User prompt
        system_prompt: System prompt
        response_format: Optional JSON schema for structured output

    Returns:
        Parsed JSON response or None if API is unavailable
    """
    if not client:
        print("[WARN] OpenAI API key not found. Skipping AI generation.")
        return None

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    last_error: Optional[Exception] = None
    for model in _get_openai_model_candidates():
        try:
            kwargs: Dict[str, Any] = {
                "model": model,
                "messages": messages,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content

            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"content": content}

        except Exception as e:
            last_error = e
            if _should_fallback_model(e):
                print(f"[WARN] OpenAI model '{model}' unavailable. Falling back...")
                continue
            print(f"[ERROR] OpenAI API error: {e}")
            return None

    if last_error:
        print(f"[ERROR] OpenAI API error (all model candidates failed): {last_error}")
    return None


def fetch_pexels_image(query: str, orientation: str = "landscape") -> Optional[Dict[str, str]]:
    """
    Fetch an image from Pexels API.

    Args:
        query: Search query
        orientation: Image orientation (landscape, portrait, square)

    Returns:
        Dictionary with image info or None
    """
    if not PEXELS_API_KEY:
        print("[WARN] Pexels API key not found. Skipping image fetch.")
        return None

    try:
        headers = {"Authorization": PEXELS_API_KEY}
        params = {
            "query": query,
            "per_page": 1,
            "orientation": orientation,
        }

        response = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()

        data = response.json()
        if data.get("photos"):
            photo = data["photos"][0]
            return {
                "url": photo["src"]["large"],
                "alt": photo.get("alt", query),
                "photographer": photo["photographer"],
                "photographer_url": photo["photographer_url"],
                "pexels_url": photo["url"],
            }

        return None

    except Exception as e:
        print(f"[ERROR] Pexels API error: {e}")
        return None


def generate_ogp_image(
    title: str,
    series: str,
    output_path: Path,
    width: int = 1200,
    height: int = 630,
) -> bool:
    """
    Generate OGP (Open Graph Protocol) image for social media sharing.

    Args:
        title: Post title
        series: Series name
        output_path: Path to save the image
        width: Image width
        height: Image height

    Returns:
        True if successful, False otherwise
    """
    try:
        img = Image.new("RGB", (width, height), color="#1a1a2e")
        draw = ImageDraw.Draw(img)

        for i in range(height):
            r = int(26 + (52 - 26) * i / height)
            g = int(26 + (73 - 26) * i / height)
            b = int(46 + (118 - 46) * i / height)
            draw.rectangle([(0, i), (width, i + 1)], fill=(r, g, b))

        try:
            if FONT_PATH.exists():
                font_title = ImageFont.truetype(str(FONT_PATH), 60)
                font_series = ImageFont.truetype(str(FONT_PATH), 40)
            else:
                print(f"[WARN] Font not found at {FONT_PATH}. Using default font.")
                font_title = ImageFont.load_default()
                font_series = ImageFont.load_default()
        except Exception as e:
            print(f"[WARN] Error loading font: {e}. Using default font.")
            font_title = ImageFont.load_default()
            font_series = ImageFont.load_default()

        series_bbox = draw.textbbox((0, 0), series, font=font_series)
        series_width = series_bbox[2] - series_bbox[0]
        series_x = (width - series_width) // 2
        draw.text((series_x, 80), series, fill="#00d9ff", font=font_series)

        max_width = width - 100
        lines: List[str] = []
        words = title.split()
        current_line = ""

        for word in words:
            test_line = current_line + word
            bbox = draw.textbbox((0, 0), test_line, font=font_title)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word

        if current_line:
            lines.append(current_line)

        lines = lines[:3]

        y_offset = (height - len(lines) * 80) // 2
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_title)
            line_width = bbox[2] - bbox[0]
            x = (width - line_width) // 2
            draw.text((x, y_offset), line, fill="#ffffff", font=font_title)
            y_offset += 80

        output_path.parent.mkdir(parents=True, exist_ok=True)

        img.save(output_path, "PNG", optimize=True)
        print(f"[OK] OGP image generated: {output_path}")
        return True

    except Exception as e:
        print(f"[ERROR] Error generating OGP image: {e}")
        return False


def generate_hash(text: str) -> str:
    """Generate SHA-1 hash of text."""
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def build_amazon_url(asin: str) -> str:
    """Build Amazon affiliate URL."""
    if not asin:
        return ""
    base_url = f"https://www.amazon.co.jp/dp/{asin}"
    if AMAZON_TAG:
        return f"{base_url}?tag={AMAZON_TAG}"
    return base_url


def build_rakuten_url(params: str) -> str:
    """Build Rakuten affiliate URL."""
    if not params:
        return ""
    return f"https://hb.afl.rakuten.co.jp/{params}"


def sanitize_filename(text: str) -> str:
    """Sanitize text for use in filenames."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        text = text.replace(char, "")
    return text.strip()
