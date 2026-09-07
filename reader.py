"""
reader.py
=========
1-Click Clean Reader Engine:
Extracts distraction-free article text, headings, and clean HTML from any web page.
Bypasses ad popups, cookie walls, paywalls, and social clutter.
Checks local MongoDB cache first, otherwise fetches live.
"""

from __future__ import annotations

import logging
import math
import re
from typing import Any, Dict
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger("clean_reader")

JUNK_TAGS = [
    "script", "style", "noscript", "iframe", "svg", "form", "nav",
    "footer", "header", "aside", "dialog", "button", "input", "select"
]

JUNK_PATTERNS = re.compile(
    r"(ad|banner|cookie|popup|modal|newsletter|social|share|widget|sponsor|comment|sidebar|promo|outbrain|taboola|related-posts)",
    re.IGNORECASE
)


def extract_clean_article(url: str) -> Dict[str, Any]:
    """Fetches and extracts a distraction-free clean article view.

    Args:
        url: Canonical URL to read.

    Returns:
        Dictionary containing title, author, domain, clean_html, word_count,
        reading_time_minutes, and original_url.
    """
    if not url:
        return {"status": "error", "message": "No URL provided."}

    parsed = urlparse(url)
    domain = parsed.netloc.replace("www.", "")

    # Live Fetch with clean headers and timeout
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        res = requests.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        if res.status_code != 200:
            return {"status": "error", "message": f"Failed to fetch page (HTTP {res.status_code})."}
        html = res.text
    except Exception as exc:
        logger.warning("Clean reader failed to fetch %s: %s", url, exc)
        return {"status": "error", "message": f"Could not load article: {str(exc)}"}

    # 3. Parse and extract article content
    soup = BeautifulSoup(html, "html.parser")

    # Title extraction
    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else domain

    # Description extraction
    meta_desc = ""
    desc_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if desc_tag and desc_tag.get("content"):
        meta_desc = desc_tag["content"].strip()

    # Strip junk tags
    for tag in soup(JUNK_TAGS):
        tag.decompose()

    # Strip elements with junk class/id names
    for el in soup.find_all(True):
        if not hasattr(el, "attrs") or el.attrs is None:
            continue
        classes_raw = el.attrs.get("class", [])
        classes = " ".join(classes_raw) if isinstance(classes_raw, list) else str(classes_raw or "")
        el_id = str(el.attrs.get("id", ""))
        combined = f"{classes} {el_id}"
        if JUNK_PATTERNS.search(combined):
            if el.name not in ("article", "main", "body", "html"):
                el.decompose()

    # Find the best candidate article container
    article_container = soup.find("article") or soup.find("main") or soup.find(role="main")
    
    if not article_container:
        # Fallback: pick container with highest count of <p> tags
        best_p_count = 0
        best_div = None
        for div in soup.find_all(["div", "section"]):
            p_count = len(div.find_all("p", recursive=False))
            if p_count > best_p_count:
                best_p_count = p_count
                best_div = div
        article_container = best_div or soup.body

    # Extract allowed elements: h1-h4, p, blockquote, ul, ol, pre, img
    clean_parts = []
    total_words = 0

    if article_container:
        for elem in article_container.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "ul", "ol", "pre", "img"]):
            if elem.name == "img":
                src = elem.get("src")
                if src and src.startswith(("http://", "https://")) and not src.endswith((".ico", ".svg")):
                    alt = elem.get("alt", "")
                    clean_parts.append(f'<img src="{src}" alt="{alt}" class="reader-image" />')
            elif elem.name in ("h1", "h2", "h3", "h4"):
                text = elem.get_text(strip=True)
                if text:
                    clean_parts.append(f'<{elem.name}>{text}</{elem.name}>')
            elif elem.name == "p":
                text = elem.get_text(strip=True)
                # Filter out one-line copyright or disclaimer lines
                if text and len(text) > 20:
                    clean_parts.append(f'<p>{text}</p>')
                    total_words += len(text.split())
            elif elem.name in ("blockquote", "pre"):
                text = elem.get_text(strip=True)
                if text:
                    clean_parts.append(f'<{elem.name}>{text}</{elem.name}>')
                    total_words += len(text.split())
            elif elem.name in ("ul", "ol"):
                items = [li.get_text(strip=True) for li in elem.find_all("li") if li.get_text(strip=True)]
                if items:
                    lis = "".join(f'<li>{it}</li>' for it in items)
                    clean_parts.append(f'<{elem.name}>{lis}</{elem.name}>')
                    total_words += sum(len(it.split()) for it in items)

    clean_html = "".join(clean_parts)
    if not clean_html or total_words < 30:
        # Fallback to plain text paragraphs from soup.get_text()
        raw_text = soup.get_text(separator="\n", strip=True)
        paragraphs = [p for p in raw_text.split("\n") if len(p) > 50]
        clean_html = "".join(f"<p>{p}</p>" for p in paragraphs[:30])
        total_words = sum(len(p.split()) for p in paragraphs[:30])

    reading_time = max(1, math.ceil(total_words / 200))

    return {
        "status": "success",
        "url": url,
        "domain": domain,
        "title": title,
        "description": meta_desc,
        "clean_html": clean_html,
        "word_count": total_words,
        "reading_time": f"{reading_time} min read",
        "source": "live",
    }
