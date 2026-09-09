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


COMMON_BANGS = {
    "!w": "https://en.wikipedia.org/wiki/Special:Search?search={}",
    "!wiki": "https://en.wikipedia.org/wiki/Special:Search?search={}",
    "!yt": "https://www.youtube.com/results?search_query={}",
    "!youtube": "https://www.youtube.com/results?search_query={}",
    "!g": "https://www.google.com/search?q={}",
    "!google": "https://www.google.com/search?q={}",
    "!gh": "https://github.com/search?q={}",
    "!github": "https://github.com/search?q={}",
    "!r": "https://www.reddit.com/search/?q={}",
    "!reddit": "https://www.reddit.com/search/?q={}",
    "!a": "https://www.amazon.com/s?k={}",
    "!amazon": "https://www.amazon.com/s?k={}",
    "!m": "https://www.google.com/maps/search/{}",
    "!maps": "https://www.google.com/maps/search/{}",
    "!tw": "https://twitter.com/search?q={}",
    "!twitter": "https://twitter.com/search?q={}",
    "!x": "https://x.com/search?q={}",
    "!so": "https://stackoverflow.com/search?q={}",
    "!imdb": "https://www.imdb.com/find?q={}",
    "!sp": "https://open.spotify.com/search/{}",
    "!spotify": "https://open.spotify.com/search/{}",
    "!ddg": "https://duckduckgo.com/?q={}",
}


def resolve_bang(query: str) -> Optional[str]:
    """Resolves DuckDuckGo !bang shortcuts natively, with live DDG 303 fallback."""
    if not query:
        return None
    tokens = query.strip().split()
    bang_token = None
    remaining_tokens = []
    for t in tokens:
        if t.startswith("!") and len(t) > 1 and not bang_token:
            bang_token = t.lower()
        else:
            remaining_tokens.append(t)

    if not bang_token:
        return None

    clean_q = requests.utils.quote(" ".join(remaining_tokens))
    # 1. Fast local dictionary lookup for instant speed
    if bang_token in COMMON_BANGS:
        template = COMMON_BANGS[bang_token]
        return template.format(clean_q)

    # 2. Live DuckDuckGo API 303 redirect lookup for all other 13,000+ bangs
    try:
        url = f"https://api.duckduckgo.com/?q={requests.utils.quote(query)}&format=json"
        res = requests.get(url, allow_redirects=False, timeout=2.5)
        if res.status_code in (301, 302, 303, 307) and "Location" in res.headers:
            return res.headers["Location"]
    except Exception:
        pass
    return None


def get_instant_answer(query: str) -> Optional[Dict[str, Any]]:
    """Queries DuckDuckGo's Instant Answer API for encyclopedic entity data."""
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

        # Extract DuckDuckGo Subtitle (Wikidata description or Entity)
        subtitle = infobox_data.get("Wikidata description") or data.get("Entity") or ""

        # Extract official / direct website results if available
        official_sites = []
        for res_item in data.get("Results", []):
            if isinstance(res_item, dict) and res_item.get("FirstURL"):
                first_url = res_item["FirstURL"]
                raw_text = res_item.get("Text", "")
                official_sites.append({
                    "url": first_url,
                    "title": raw_text or heading or query.title(),
                    "snippet": f"Official website for {heading or query.title()}.",
                })

        official_url = ""
        if official_sites:
            official_url = official_sites[0]["url"]
        elif infobox_data.get("Official Website"):
            official_url = infobox_data["Official Website"].strip("[]")
        elif infobox_data.get("Website"):
            raw_w = infobox_data["Website"].strip("[]")
            official_url = raw_w if raw_w.startswith("http") else f"https://{raw_w}"

        # Build DuckDuckGo-style Quick Links pills
        quick_links = []
        if official_url:
            quick_links.append({"name": "Website", "url": official_url, "icon": "globe"})
        wiki_url = data.get("AbstractURL")
        if wiki_url and "wikipedia.org" in wiki_url:
            quick_links.append({"name": "Wikipedia", "url": wiki_url, "icon": "wikipedia"})
        if "Instagram profile" in infobox_data:
            handle = infobox_data["Instagram profile"].strip("[]")
            quick_links.append({"name": "Instagram", "url": f"https://instagram.com/{handle}", "icon": "instagram"})
        if "Facebook profile" in infobox_data:
            handle = infobox_data["Facebook profile"].strip("[]")
            quick_links.append({"name": "Facebook", "url": f"https://facebook.com/{handle}", "icon": "facebook"})
        if "Youtube channel" in infobox_data:
            ch = infobox_data["Youtube channel"].strip("[]")
            quick_links.append({"name": "YouTube", "url": f"https://youtube.com/channel/{ch}", "icon": "youtube"})
        if "GitHub profile" in infobox_data:
            gh = infobox_data["GitHub profile"].strip("[]")
            quick_links.append({"name": "GitHub", "url": f"https://github.com/{gh}", "icon": "github"})
        if "Twitter profile" in infobox_data:
            tw = infobox_data["Twitter profile"].strip("[]")
            quick_links.append({"name": "X", "url": f"https://x.com/{tw}", "icon": "twitter"})

        return {
            "heading": heading or query.title(),
            "subtitle": subtitle,
            "official_url": official_url,
            "abstract": abstract,
            "image_url": image_url,
            "source": data.get("AbstractSource", "DuckDuckGo & Wikipedia"),
            "source_url": data.get("AbstractURL", ""),
            "entity_type": data.get("Entity", ""),
            "quick_links": quick_links,
            "related_nodes": related_nodes,
            "infobox": infobox_data,
            "official_sites": official_sites,
            "answer": data.get("Answer", ""),
            "answer_type": data.get("AnswerType", ""),
            "definition": data.get("Definition", ""),
        }

    except Exception as exc:
        logger.debug("DuckDuckGo Instant Answer lookup error for '%s': %s", query, exc)
        return None
