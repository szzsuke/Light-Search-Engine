"""
ddg_knowledge.py
================
DuckDuckGo Instant Answer & Knowledge Graph Integration:
Provides rich encyclopedic summaries, entity hero images, infobox facts,
and interactive pivot topics directly from DuckDuckGo's official open API.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import requests

logger = logging.getLogger("ddg_knowledge")

DDG_API_URL = "https://api.duckduckgo.com/"


_CREATOR_ALIASES = {
    "szzsuke",
    "@szzsuke",
    "szzsuke.",
    "nishkarsh",
    "nishkarsh shrivastava",
    "maker of light",
    "maker of light search",
    "maker of light search engine",
    "creator of light search engine",
    "creator of light",
    "who made light search engine",
    "who created light search engine",
    "who is szzsuke",
}


def _get_creator_knowledge_panel() -> Dict[str, Any]:
    return {
        "heading": "Nishkarsh Shrivastava",
        "handle": "@szzsuke",
        "badge": "Maker of Light Search Engine",
        "is_creator": True,
        "abstract": "Nishkarsh Shrivastava (known online as szzsuke) is an Indian software developer, creative technologist, and the creator of Light Search Engine. He specializes in search engineering, interactive 3D web graphics, and high-performance computational systems.",
        "image_url": "assets/szzsuke.jpg",
        "fallback_image_url": "https://avatars.githubusercontent.com/u/222186582?v=4",
        "source": "GitHub Profile & Portfolio",
        "source_url": "https://github.com/szzsuke",
        "entity_type": "Software Developer & Creator",
        "infobox": {
            "Role": "Maker of Light Search Engine",
            "Known As": "szzsuke",
            "Location": "Bhubaneswar, Odisha, India",
            "Key Projects": "Light Search Engine, AstraLine, VTOP-Auto",
        },
        "social_links": [
            {"name": "GitHub", "url": "https://github.com/szzsuke", "icon": "github"},
            {"name": "LinkedIn", "url": "https://www.linkedin.com/in/szzsuke/", "icon": "linkedin"},
            {"name": "X", "url": "https://x.com/nishkarsh005", "icon": "twitter"},
            {"name": "Instagram", "url": "https://www.instagram.com/szzsuke", "icon": "instagram"},
            {"name": "LeetCode", "url": "https://leetcode.com/u/szzsuke/", "icon": "code"},
            {"name": "Sketchfab", "url": "https://sketchfab.com/Szzsuke", "icon": "box"},
        ],
    }


def get_instant_answer(query: str) -> Optional[Dict[str, Any]]:
    """Queries DuckDuckGo's Instant Answer API for encyclopedic entity data.

    Args:
        query: User search query string.

    Returns:
        Structured knowledge dictionary, or None if no entity is matched.
    """
    if not query or len(query.strip()) < 2:
        return None

    clean_q = query.strip().lower()
    if clean_q in _CREATOR_ALIASES or clean_q.replace(" ", "") == "szzsuke" or "szzsuke" in clean_q:
        return _get_creator_knowledge_panel()

    try:
        params = {
            "q": query.strip(),
            "format": "json",
            "no_html": "1",
            "skip_disambig": "1",
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        }
        res = requests.get(DDG_API_URL, params=params, headers=headers, timeout=3.5)
        if res.status_code != 200:
            return None

        data = res.json()
        heading = data.get("Heading", "").strip()
        abstract = data.get("AbstractText", "") or data.get("Abstract", "")
        abstract = abstract.strip()

        # If neither abstract nor heading has substantive data, skip
        if not heading and not abstract:
            return None

        # Build full image URL
        image_path = data.get("Image", "")
        image_url = ""
        if image_path:
            if image_path.startswith("http"):
                image_url = image_path
            else:
                image_url = f"https://duckduckgo.com{image_path}"

        # Extract related entity topics for interactive pivot tags
        related_nodes: List[Dict[str, str]] = []
        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict) and topic.get("Text"):
                text = topic.get("Text", "").strip()
                # DuckDuckGo related topics format: "Name - Description"
                name = text.split(" - ")[0] if " - " in text else text[:30]
                node_url = topic.get("FirstURL", "")
                icon = topic.get("Icon", {}).get("URL", "")
                if icon and not icon.startswith("http"):
                    icon = f"https://duckduckgo.com{icon}"
                related_nodes.append({
                    "name": name,
                    "description": text,
                    "url": node_url,
                    "icon": icon,
                })
            if len(related_nodes) >= 6:
                break

        # Extract infobox attributes if available
        infobox_data = {}
        raw_infobox = data.get("Infobox", {})
        if isinstance(raw_infobox, dict) and "content" in raw_infobox:
            for item in raw_infobox.get("content", []):
                if isinstance(item, dict) and item.get("label") and item.get("value"):
                    infobox_data[item["label"]] = str(item["value"])

        return {
            "heading": heading or query.title(),
            "abstract": abstract,
            "image_url": image_url,
            "source": data.get("AbstractSource", "DuckDuckGo & Wikipedia"),
            "source_url": data.get("AbstractURL", ""),
            "entity_type": data.get("Entity", ""),
            "related_nodes": related_nodes,
            "infobox": infobox_data,
        }

    except Exception as exc:
        logger.debug("DuckDuckGo Instant Answer lookup error for '%s': %s", query, exc)
        return None
