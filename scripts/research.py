#!/usr/bin/env python3
"""
Lightweight web research helpers (safe-by-default).

- Uses Google News RSS search to discover candidate URLs for allow-listed sources.
- Fetches each URL and extracts OGP metadata (title/description) only.
- Does NOT store or pass full article text to the model (reduces copying risk and token cost).
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus, urlparse

import feedparser
import requests


RESEARCH_ENABLED = os.getenv("RESEARCH_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")
RESEARCH_TIMEOUT_SEC = float(os.getenv("RESEARCH_TIMEOUT_SEC", "8"))
RESEARCH_MAX_LINKS = int(os.getenv("RESEARCH_MAX_LINKS", "4"))
RESEARCH_PER_SOURCE = int(os.getenv("RESEARCH_PER_SOURCE", "1"))

UA = os.getenv("RESEARCH_USER_AGENT", "manga-kousatsu-hub/1.0 (+https://github.com/pontarou0610/manga-kousatsu-hub)")


_META_RE = re.compile(r'<meta[^>]+>', re.IGNORECASE)
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_RE = re.compile(r'property=["\\\']og:title["\\\'][^>]*content=["\\\'](.*?)["\\\']', re.IGNORECASE | re.DOTALL)
_OG_DESC_RE = re.compile(r'property=["\\\']og:description["\\\'][^>]*content=["\\\'](.*?)["\\\']', re.IGNORECASE | re.DOTALL)


def _strip_html(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\\s+", " ", s).strip()
    return s


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def google_news_rss(query: str) -> str:
    q = quote_plus(query)
    return f"https://news.google.com/rss/search?q={q}&hl=ja&gl=JP&ceid=JP:ja"


def discover_urls_from_google_news(domain: str, query: str, max_items: int) -> List[str]:
    rss_url = google_news_rss(f"site:{domain} {query}")
    feed = feedparser.parse(rss_url)
    urls: List[str] = []
    for entry in getattr(feed, "entries", [])[: max_items * 3]:
        link = getattr(entry, "link", "") or ""
        if not link:
            continue
        urls.append(link)
        if len(urls) >= max_items:
            break
    return urls


def _looks_like_feed(text: str) -> bool:
    head = (text or "").lstrip()[:400].lower()
    return head.startswith("<?xml") or "<rss" in head or "<feed" in head


def discover_site_feed_url(site_url: str) -> Optional[str]:
    """
    Try common RSS/Atom endpoints for a site root.
    Returns the first feed URL that looks parseable.
    """
    base = (site_url or "").strip()
    if not base:
        return None

    # Normalize: remove trailing slash for consistent concatenation.
    if base.endswith("/"):
        base = base[:-1]

    candidates = [
        base + "/feed",
        base + "/feed/",
        base + "/rss",
        base + "/rss.xml",
        base + "/atom.xml",
        base + "/index.xml",
    ]

    for url in candidates:
        try:
            resp = requests.get(url, timeout=RESEARCH_TIMEOUT_SEC, headers={"User-Agent": UA})
            if resp.status_code >= 400:
                continue
            if not _looks_like_feed(resp.text):
                continue
            feed = feedparser.parse(resp.text)
            if getattr(feed, "entries", None):
                return url
        except Exception:
            continue

    return None


def discover_urls_from_feed(feed_url: str, query: str, max_items: int) -> List[str]:
    feed = feedparser.parse(feed_url)
    scored: List[Tuple[int, str]] = []
    q = (query or "").strip()
    if not q:
        return []
    series_terms = q.split()
    must_terms = [t for t in series_terms if t and not re.search(r"\\d", t)]

    # Prefer titles that include numeric chapter markers.
    nums = re.findall(r"(\\d+)", q)
    num = nums[-1] if nums else ""
    num_re = None
    if num:
        # Prefer exact chapter patterns, avoid substring matches (e.g. "21" shouldn't match "241").
        num_re = re.compile(rf"(?:第\\s*0*{re.escape(num)}\\s*話|\\b0*{re.escape(num)}\\b)")

    for entry in getattr(feed, "entries", [])[:200]:
        title = (getattr(entry, "title", "") or "").strip()
        summary = (getattr(entry, "summary", "") or "").strip()
        hay = (title + " " + _strip_html(summary)).lower()

        if must_terms and not any(mt.lower() in hay for mt in must_terms):
            continue

        score = 0
        # Term match
        for term in series_terms:
            if term and term.lower() in hay:
                score += 2
        # Numeric chapter hint
        if num_re and num_re.search(hay):
            score += 3
        if "第" in title and "話" in title:
            score += 1

        link = getattr(entry, "link", "") or ""
        if not link:
            continue
        if score > 0:
            scored.append((score, link))

    scored.sort(key=lambda x: x[0], reverse=True)
    urls: List[str] = []
    for _, link in scored:
        if link not in urls:
            urls.append(link)
        if len(urls) >= max_items:
            break
    return urls


def fetch_og_metadata(url: str) -> Optional[Dict[str, str]]:
    try:
        resp = requests.get(url, timeout=RESEARCH_TIMEOUT_SEC, headers={"User-Agent": UA})
        if resp.status_code >= 400:
            return None
        # Best-effort: treat content as text and parse metadata only.
        html = resp.text
        final_url = resp.url or url
    except Exception:
        return None

    og_title = ""
    og_desc = ""
    title = ""

    m = _OG_TITLE_RE.search(html)
    if m:
        og_title = _strip_html(m.group(1))
    m = _OG_DESC_RE.search(html)
    if m:
        og_desc = _strip_html(m.group(1))
    m = _TITLE_RE.search(html)
    if m:
        title = _strip_html(m.group(1))

    best_title = og_title or title
    best_desc = og_desc
    if not best_title and not best_desc:
        return None

    # Keep it short.
    if len(best_title) > 140:
        best_title = best_title[:140].rstrip() + "…"
    if len(best_desc) > 180:
        best_desc = best_desc[:180].rstrip() + "…"

    return {"title": best_title, "desc": best_desc, "url": final_url}


def collect_reference_notes(
    *,
    series_name: str,
    chapter_label: str,
    sources: List[str],
) -> List[Dict[str, str]]:
    """
    Returns a list of notes: [{title, url, desc, source}].
    Sources can be direct URLs (e.g., wikipedia page) or site roots.
    """
    if not RESEARCH_ENABLED:
        return []
    if not sources:
        return []

    query = f"{series_name} {chapter_label}"
    picked_urls: List[Tuple[str, str]] = []  # (source, url)

    for src in sources:
        src = (src or "").strip()
        if not src:
            continue

        dom = _domain(src)
        # Direct page (specific path): always include as-is.
        if dom and (urlparse(src).path not in ("", "/")):
            picked_urls.append((dom, src))
            continue

        if not dom:
            continue

        # Prefer the site's own RSS/Atom feed when available.
        feed_url = discover_site_feed_url(src)
        if feed_url:
            for url in discover_urls_from_feed(feed_url, query, max_items=RESEARCH_PER_SOURCE):
                picked_urls.append((dom, url))
        else:
            # Fallback: Google News RSS search.
            for url in discover_urls_from_google_news(dom, query, max_items=RESEARCH_PER_SOURCE):
                picked_urls.append((dom, url))

    # De-duplicate, preserve order.
    seen = set()
    uniq: List[Tuple[str, str]] = []
    for dom, url in picked_urls:
        key = url.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append((dom, key))
        if len(uniq) >= RESEARCH_MAX_LINKS:
            break

    notes: List[Dict[str, str]] = []
    for dom, url in uniq:
        meta = fetch_og_metadata(url)
        if not meta:
            continue
        notes.append(
            {
                "title": meta.get("title", "") or url,
                "url": url,
                "desc": meta.get("desc", ""),
                "source": dom,
            }
        )

    return notes
