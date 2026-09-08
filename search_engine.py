"""
search_engine.py
=================
SOUL Search Engine Core Orchestrator:
- Multi-Tab Search: All (Web), Images, News, Videos.
- Brave-Style Rich Result Metadata: Site Names, Clean Breadcrumbs, High-res Favicons,
  and Media Thumbnails (e.g. YouTube videos with duration).
- Ultra-fast concurrent multi-engine retrieval (DuckDuckGo + Brave fast backends).
- Brave/Bing-quality ranking with strict Domain Diversity (Host Collapsing).
- Eliminates Wikipedia duplicates/flooding (omits from organic results if knowledge panel exists).
- Natural organic blending of authentic community discussions (Reddit/GitHub).
- DuckDuckGo Instant Answer / Knowledge Graph integration.
- In-memory fast LRU/TTL cache for instant repeated searches and pagination slices.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

import config
from ddg_knowledge import get_instant_answer
from gemini_ai import gemini_ai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared persistent thread pool for low-latency concurrent retrieval
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="soul_search")

# In-memory query result cache: (query_norm, mode) -> (timestamp, result_dict)
_QUERY_CACHE: Dict[Tuple[str, str], Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 900  # 15 minutes cache lifetime
_MAX_CACHE_ENTRIES = 512

# Low-quality SEO affiliate / spam domains to filter or demote
_BLOCKED_DOMAINS = {
    "pinterest.com",
    "bestproducts.com",
    "toptenreviews.com",
}

# Known human-friendly site names
_KNOWN_SITE_NAMES = {
    "reddit.com": "Reddit",
    "reddithelp.com": "Reddit Help",
    "support.reddithelp.com": "Reddit Help",
    "redditstatus.com": "Reddit Status",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "wikipedia.org": "Wikipedia",
    "github.com": "GitHub",
    "stackoverflow.com": "Stack Overflow",
    "twitter.com": "X (Twitter)",
    "x.com": "X (Twitter)",
    "instagram.com": "Instagram",
    "linkedin.com": "LinkedIn",
    "facebook.com": "Facebook",
    "google.com": "Google",
    "gmail.com": "Gmail",
    "mail.google.com": "Gmail",
    "medium.com": "Medium",
    "quora.com": "Quora",
    "amazon.com": "Amazon",
    "apple.com": "Apple",
    "microsoft.com": "Microsoft",
    "netflix.com": "Netflix",
    "spotify.com": "Spotify",
    "twitch.tv": "Twitch",
    "nytimes.com": "The New York Times",
    "theverge.com": "The Verge",
    "techcrunch.com": "TechCrunch",
    "bbc.com": "BBC",
    "cnn.com": "CNN",
    "reuters.com": "Reuters",
    "bloomberg.com": "Bloomberg",
}


def _get_from_cache(query: str, mode: str, safe: bool = True) -> Dict[str, Any] | None:
    key = (query.strip().lower(), mode.lower(), safe)
    if key in _QUERY_CACHE:
        ts, data = _QUERY_CACHE[key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            logger.info("Cache hit for query: '%s' [%s] (safe=%s)", query, mode, safe)
            return data
        else:
            del _QUERY_CACHE[key]
    return None


def _put_in_cache(query: str, mode: str, data: Dict[str, Any], safe: bool = True) -> None:
    if len(_QUERY_CACHE) >= _MAX_CACHE_ENTRIES:
        oldest_keys = sorted(_QUERY_CACHE.keys(), key=lambda k: _QUERY_CACHE[k][0])[:100]
        for k in oldest_keys:
            _QUERY_CACHE.pop(k, None)
    key = (query.strip().lower(), mode.lower(), safe)
    _QUERY_CACHE[key] = (time.time(), data)


def get_root_domain(url: str) -> str:
    """Extracts root domain for host collapsing and domain diversity."""
    try:
        netloc = urlparse(url).netloc.lower().replace("www.", "")
        parts = netloc.split(".")
        if len(parts) >= 2:
            if "wikipedia" in parts:
                return "wikipedia.org"
            if len(parts) > 2:
                return f"{parts[-2]}.{parts[-1]}"
        return netloc
    except Exception:
        return url


def extract_site_info(url: str, title: str = "", body: str = "") -> Dict[str, Any]:
    """Extracts Brave-style rich metadata: site name, breadcrumbs, favicon, and video thumbnails."""
    p = urlparse(url)
    host = p.netloc.replace("www.", "").lower()
    
    # Clean breadcrumb path segments
    path_clean = p.path.strip("/")
    raw_segments = [s for s in path_clean.split("/") if s and len(s) < 32 and not s.startswith(("?", "&", "="))]
    breadcrumb = " › ".join([host] + raw_segments) if raw_segments else host

    # Site Name heuristics
    site_name = _KNOWN_SITE_NAMES.get(host)
    if not site_name:
        for k, v in _KNOWN_SITE_NAMES.items():
            if host.endswith("." + k) or host == k:
                site_name = v
                break
    if not site_name:
        parts = host.split(".")
        main_part = parts[-2] if len(parts) >= 2 else parts[0]
        site_name = main_part.capitalize()

    # Favicon via high-res Google/DDG service
    favicon = f"https://www.google.com/s2/favicons?domain={host}&sz=64"

    # YouTube and Video Detection
    thumbnail = ""
    is_video = False
    duration = ""
    
    if "youtube.com" in host or "youtu.be" in host:
        is_video = True
        vid_match = re.search(r"(?:v=|\/shorts\/|\/embed\/|youtu\.be\/)([a-zA-Z0-9_-]{11})", url)
        if vid_match:
            vid = vid_match.group(1)
            thumbnail = f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"

    # Check for date in snippet
    published = ""
    date_match = re.search(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}|\d{1,2} (?:hours?|days?|months?|years?|mins?|minutes?) ago)\b", body, re.IGNORECASE)
    if date_match:
        published = date_match.group(1)

    return {
        "site_name": site_name,
        "breadcrumb": breadcrumb,
        "favicon": favicon,
        "is_video": is_video,
        "thumbnail": thumbnail,
        "duration": duration,
        "published": published,
    }


def _fetch_ddg_html_pages(query: str, max_pages: int = 3, safe: bool = True) -> List[Dict[str, Any]]:
    """Fetches continuous real results directly from DuckDuckGo HTML without rate limits."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    s = requests.Session()
    kp_val = "1" if safe else "-1"
    s.cookies.set("p", kp_val, domain="duckduckgo.com")
    s.cookies.set("p", kp_val, domain="html.duckduckgo.com")
    all_results = []
    try:
        r = s.get(f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}", headers=headers, timeout=5)
        if r.status_code != 200:
            return all_results

        soup = BeautifulSoup(r.text, "html.parser")
        for page_idx in range(1, max_pages + 1):
            for res in soup.select(".result"):
                t_el = res.select_one(".result__title a")
                s_el = res.select_one(".result__snippet")
                if not t_el:
                    continue
                raw_href = t_el.get("href", "")
                parsed = parse_qs(urlparse(raw_href).query)
                final_url = parsed.get("uddg", [raw_href])[0]
                if final_url.startswith("http"):
                    all_results.append({
                        "title": t_el.get_text(strip=True),
                        "href": final_url,
                        "body": s_el.get_text(strip=True) if s_el else "",
                    })

            inputs = {inp.get("name"): inp.get("value") for inp in soup.select(".nav-link form input") if inp.get("name")}
            if not inputs or page_idx == max_pages:
                break

            r_next = s.post("https://html.duckduckgo.com/html/", data=inputs, headers=headers, timeout=5)
            if r_next.status_code != 200:
                break
            soup = BeautifulSoup(r_next.text, "html.parser")
    except Exception as exc:
        logger.warning("DDG HTML scraper error for '%s': %s", query, exc)

    return all_results


def _safe_ddgs_search(query: str, max_results: int = 30, page: int = 1, safe: bool = True) -> List[Dict[str, Any]]:
    """Fetches web results using direct fast backends with page parameter."""
    ss_val = "moderate" if safe else "off"
    try:
        results = list(DDGS(timeout=5).text(query, page=page, max_results=max_results, safesearch=ss_val))
        if results:
            return results
    except Exception as exc:
        logger.warning("Search error for '%s' (page %d): %s", query, page, exc)

    try:
        return list(DDGS(timeout=4).text(query, max_results=max_results, safesearch=ss_val))
    except Exception as exc:
        logger.warning("Fallback DDGS search error for '%s': %s", query, exc)
        return []


class SearchEngine:
    """Orchestrates multi-tab search with Brave-style rich result cards and infinite scroll."""

    def search_images(self, query: str, max_results: int = 80, safe: bool = True) -> List[Dict[str, Any]]:
        """Fetches images using DDGS with thumbnail and dimensions."""
        try:
            raw = list(DDGS(timeout=6).images(query, max_results=max_results, safesearch="moderate" if safe else "off"))
            results = []
            for r in raw:
                u = r.get("url") or r.get("image") or ""
                host = urlparse(u).netloc.replace("www.", "").lower()
                results.append({
                    "title": r.get("title", ""),
                    "image": r.get("image", ""),
                    "thumbnail": r.get("thumbnail") or r.get("image", ""),
                    "url": u,
                    "width": r.get("width", ""),
                    "height": r.get("height", ""),
                    "source": r.get("source", host),
                    "domain": host,
                    "favicon": f"https://www.google.com/s2/favicons?domain={host}&sz=64",
                })
            return results
        except Exception as exc:
            logger.warning("Image search error for '%s': %s", query, exc)
            return []

    def search_news(self, query: str, max_results: int = 60, safe: bool = True) -> List[Dict[str, Any]]:
        """Fetches live news headlines using DDGS."""
        try:
            raw = list(DDGS(timeout=6).news(query, max_results=max_results, safesearch="moderate" if safe else "off"))
            results = []
            for r in raw:
                u = r.get("url", "")
                host = urlparse(u).netloc.replace("www.", "").lower()
                site_info = extract_site_info(u, r.get("title", ""), r.get("body", ""))
                results.append({
                    "title": r.get("title", ""),
                    "url": u,
                    "snippet": r.get("body", ""),
                    "date": r.get("date", ""),
                    "thumbnail": r.get("image", ""),
                    "source": r.get("source", site_info["site_name"]),
                    "site_name": r.get("source", site_info["site_name"]),
                    "breadcrumb": site_info["breadcrumb"],
                    "favicon": site_info["favicon"],
                    "domain": host,
                })
            return results
        except Exception as exc:
            logger.warning("News search error for '%s': %s", query, exc)
            return []

    def search_videos(self, query: str, max_results: int = 50, safe: bool = True) -> List[Dict[str, Any]]:
        """Fetches video results using DDGS videos or fallback to YouTube query."""
        results = []
        try:
            raw = list(DDGS(timeout=5).videos(query, max_results=max_results, safesearch="moderate" if safe else "off"))
            for r in raw:
                u = r.get("content", "") or r.get("url", "")
                host = urlparse(u).netloc.replace("www.", "").lower()
                imgs = r.get("images", {})
                thumb = imgs.get("medium") or imgs.get("large") or imgs.get("small") or ""
                site_info = extract_site_info(u, r.get("title", ""), r.get("description", ""))
                
                results.append({
                    "title": r.get("title", ""),
                    "url": u,
                    "snippet": r.get("description", ""),
                    "thumbnail": thumb or site_info["thumbnail"],
                    "duration": r.get("duration", ""),
                    "published": r.get("published", "") or site_info["published"],
                    "publisher": r.get("publisher", "YouTube"),
                    "views": r.get("statistics", {}).get("viewCount", ""),
                    "site_name": r.get("publisher", site_info["site_name"]),
                    "breadcrumb": site_info["breadcrumb"],
                    "favicon": site_info["favicon"],
                    "domain": host,
                    "is_video": True,
                })
        except Exception as exc:
            logger.warning("DDGS videos error, falling back to YouTube text query: %s", exc)

        if not results:
            try:
                raw_yt = _safe_ddgs_search(f"{query} site:youtube.com", max_results=20, page=1, safe=safe)
                for r in raw_yt:
                    u = r.get("href", "")
                    site_info = extract_site_info(u, r.get("title", ""), r.get("body", ""))
                    results.append({
                        "title": r.get("title", ""),
                        "url": u,
                        "snippet": r.get("body", ""),
                        "thumbnail": site_info["thumbnail"],
                        "duration": "Video",
                        "published": site_info["published"],
                        "publisher": "YouTube",
                        "site_name": "YouTube",
                        "breadcrumb": site_info["breadcrumb"],
                        "favicon": site_info["favicon"],
                        "domain": "youtube.com",
                        "is_video": True,
                    })
            except Exception as exc2:
                logger.warning("YouTube fallback error: %s", exc2)

        return results

    def search(self, query: str, top_n: int = 60, offset: int = 0, limit: int = 10, mode: str = "all", safe: bool = True) -> Dict[str, Any]:
        """Executes a multi-tab search pipeline with deep infinite pagination and domain diversity."""
        original_query = query
        mode_clean = mode.lower() if mode else "all"

        if not query or not query.strip():
            return {
                "original_query": original_query,
                "corrected_query": "",
                "ai_summary": "",
                "knowledge_panel": None,
                "mode": mode_clean,
                "total_results": 0,
                "offset": offset,
                "limit": limit,
                "has_more": False,
                "safe": safe,
                "results": [],
            }

        # Check Cache
        cached = _get_from_cache(original_query, mode_clean, safe=safe)
        if cached:
            all_results = cached.get("all_results", [])

            # Dynamic infinite scroll page loader: If scrolling near the end, fetch next pages on demand!
            if mode_clean == "all" and (offset + limit) >= len(all_results) and len(all_results) < 250:
                try:
                    more_raw = _fetch_ddg_html_pages(original_query, max_pages=3, safe=safe)
                    if not more_raw:
                        next_page = (len(all_results) // 15) + 1
                        more_raw = _safe_ddgs_search(original_query, max_results=30, page=next_page, safe=safe)
                    seen_urls = {item["url"] for item in all_results}
                    more_items = []
                    for r in more_raw:
                        u = r.get("href", "")
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            meta = extract_site_info(u, r.get("title", ""), r.get("body", ""))
                            more_items.append({
                                "url": u,
                                "title": r.get("title", ""),
                                "snippet": r.get("body", ""),
                                "domain": urlparse(u).netloc.replace("www.", "").lower(),
                                **meta,
                            })
                    all_results.extend(more_items)
                    for rank, item in enumerate(all_results, start=1):
                        item["rank"] = rank
                    cached["all_results"] = all_results
                except Exception as ex:
                    logger.warning("Dynamic page expansion error: %s", ex)

            page_results = all_results[offset : offset + limit]
            return {
                "original_query": original_query,
                "corrected_query": cached.get("corrected_query", original_query),
                "ai_summary": cached.get("ai_summary", ""),
                "knowledge_panel": cached.get("knowledge_panel") if (offset == 0 and mode_clean == "all") else None,
                "mode": mode_clean,
                "total_results": len(all_results),
                "offset": offset,
                "limit": limit,
                "has_more": len(all_results) > (offset + limit) or (len(all_results) >= offset and len(all_results) < 180),
                "safe": safe,
                "results": page_results,
            }

        # Handle Images Mode
        if mode_clean == "images":
            img_results = self.search_images(original_query, max_results=80, safe=safe)
            _put_in_cache(original_query, mode_clean, {
                "all_results": img_results,
                "corrected_query": original_query,
                "knowledge_panel": None,
                "ai_summary": "",
            }, safe=safe)
            return {
                "original_query": original_query,
                "corrected_query": original_query,
                "knowledge_panel": None,
                "mode": mode_clean,
                "total_results": len(img_results),
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < len(img_results),
                "safe": safe,
                "results": img_results[offset : offset + limit],
            }

        # Handle News Mode
        if mode_clean == "news":
            news_results = self.search_news(original_query, max_results=60, safe=safe)
            _put_in_cache(original_query, mode_clean, {
                "all_results": news_results,
                "corrected_query": original_query,
                "knowledge_panel": None,
                "ai_summary": "",
            }, safe=safe)
            return {
                "original_query": original_query,
                "corrected_query": original_query,
                "knowledge_panel": None,
                "mode": mode_clean,
                "total_results": len(news_results),
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < len(news_results),
                "safe": safe,
                "results": news_results[offset : offset + limit],
            }

        # Handle Videos Mode
        if mode_clean == "videos":
            vid_results = self.search_videos(original_query, max_results=50, safe=safe)
            _put_in_cache(original_query, mode_clean, {
                "all_results": vid_results,
                "corrected_query": original_query,
                "knowledge_panel": None,
                "ai_summary": "",
            }, safe=safe)
            return {
                "original_query": original_query,
                "corrected_query": original_query,
                "knowledge_panel": None,
                "mode": mode_clean,
                "total_results": len(vid_results),
                "offset": offset,
                "limit": limit,
                "has_more": (offset + limit) < len(vid_results),
                "safe": safe,
                "results": vid_results[offset : offset + limit],
            }

        # Mode "all" (Web search with deep multi-page retrieval)
        fut_kp = _EXECUTOR.submit(get_instant_answer, original_query)
        fut_spell = _EXECUTOR.submit(gemini_ai.spell_check, original_query)
        
        # Concurrently fetch DuckDuckGo HTML deep pages + DDGS text search + Reddit
        fut_html = _EXECUTOR.submit(_fetch_ddg_html_pages, original_query, 3, safe)
        fut_ddgs = _EXECUTOR.submit(_safe_ddgs_search, original_query, 25, 1, safe)
        fut_reddit = _EXECUTOR.submit(_safe_ddgs_search, f"{original_query} site:reddit.com", 15, 1, safe)

        web_results: List[Dict[str, Any]] = []
        try:
            html_items = fut_html.result(timeout=6.0)
            web_results.extend(html_items)
        except Exception as exc:
            logger.warning("DDG HTML retrieval error: %s", exc)

        try:
            ddgs_items = fut_ddgs.result(timeout=4.5)
            web_results.extend(ddgs_items)
        except Exception as exc:
            logger.warning("DDGS retrieval error: %s", exc)

        reddit_results: List[Dict[str, Any]] = []
        try:
            reddit_results = fut_reddit.result(timeout=4.5)
        except Exception as exc:
            logger.warning("Reddit retrieval error: %s", exc)

        knowledge_panel = None
        try:
            knowledge_panel = fut_kp.result(timeout=1.5)
        except Exception:
            pass

        corrected_query = original_query
        try:
            corrected_query = fut_spell.result(timeout=0.8)
        except Exception:
            corrected_query = original_query

        # Domain Diversity & Host Collapsing
        is_reddit_query = "reddit" in original_query.lower()
        max_reddit_allowed = 12 if is_reddit_query else 3

        domain_counts: Dict[str, int] = {}
        seen_urls: set[str] = set()
        blended_results: List[Dict[str, Any]] = []
        saved_wiki_item = None

        clean_reddit = []
        for r in reddit_results:
            u = r.get("href", "")
            if u and "reddit.com" in u and u not in seen_urls:
                clean_reddit.append(r)

        reddit_inserted = 0
        web_inserted = 0

        # Pass 1: Strict Domain Diversity (up to 2 per root domain)
        for r in web_results:
            url = r.get("href", "")
            if not url or url in seen_urls:
                continue

            root_dom = get_root_domain(url)
            display_dom = urlparse(url).netloc.replace("www.", "").lower()

            if any(spam in root_dom for spam in _BLOCKED_DOMAINS):
                continue

            # Wikipedia deduplication logic
            if root_dom == "wikipedia.org":
                if knowledge_panel is not None:
                    continue
                elif saved_wiki_item is None:
                    site_meta = extract_site_info(url, r.get("title", ""), r.get("body", ""))
                    saved_wiki_item = {
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "domain": display_dom,
                        **site_meta,
                    }
                    seen_urls.add(url)
                    continue

            current_count = domain_counts.get(root_dom, 0)
            if root_dom == "reddit.com" and current_count >= max_reddit_allowed:
                continue
            if current_count >= 2:
                continue

            seen_urls.add(url)
            domain_counts[root_dom] = current_count + 1
            site_meta = extract_site_info(url, r.get("title", ""), r.get("body", ""))

            blended_results.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "domain": display_dom,
                **site_meta,
            })
            web_inserted += 1

            # Insert demoted Wikipedia around rank 5 or 6 if held
            if saved_wiki_item and len(blended_results) == 5:
                blended_results.append(saved_wiki_item)
                saved_wiki_item = None

            # Blend authentic Reddit discussion
            if web_inserted % 3 == 0 and clean_reddit and reddit_inserted < max_reddit_allowed:
                for red in clean_reddit:
                    r_url = red.get("href", "")
                    if r_url and r_url not in seen_urls and domain_counts.get("reddit.com", 0) < max_reddit_allowed:
                        seen_urls.add(r_url)
                        domain_counts["reddit.com"] = domain_counts.get("reddit.com", 0) + 1
                        r_meta = extract_site_info(r_url, red.get("title", ""), red.get("body", ""))
                        blended_results.append({
                            "url": r_url,
                            "title": red.get("title", ""),
                            "snippet": red.get("body", ""),
                            "domain": "reddit.com",
                            **r_meta,
                        })
                        reddit_inserted += 1
                        break

        # Append saved wiki if still held
        if saved_wiki_item and knowledge_panel is None:
            blended_results.append(saved_wiki_item)
            saved_wiki_item = None

        # Pass 2: Secondary Diverse Fill
        for r in web_results:
            if len(blended_results) >= 150:
                break
            url = r.get("href", "")
            if not url or url in seen_urls:
                continue
            root_dom = get_root_domain(url)
            display_dom = urlparse(url).netloc.replace("www.", "").lower()
            if root_dom == "wikipedia.org":
                continue
            if any(spam in root_dom for spam in _BLOCKED_DOMAINS):
                continue
            if domain_counts.get(root_dom, 0) < 4:
                seen_urls.add(url)
                domain_counts[root_dom] = domain_counts.get(root_dom, 0) + 1
                site_meta = extract_site_info(url, r.get("title", ""), r.get("body", ""))
                blended_results.append({
                    "url": url,
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "domain": display_dom,
                    **site_meta,
                })

        for rank, item in enumerate(blended_results, start=1):
            item["rank"] = rank

        cache_data = {
            "all_results": blended_results,
            "corrected_query": corrected_query,
            "knowledge_panel": knowledge_panel,
            "ai_summary": "",
        }
        if blended_results:
            _put_in_cache(original_query, mode_clean, cache_data, safe=safe)

        page_results = blended_results[offset : offset + limit]

        return {
            "original_query": original_query,
            "corrected_query": corrected_query,
            "ai_summary": "",
            "knowledge_panel": knowledge_panel if offset == 0 else None,
            "mode": mode_clean,
            "total_results": len(blended_results),
            "offset": offset,
            "limit": limit,
            "has_more": len(blended_results) > (offset + limit) or (len(blended_results) >= offset and len(blended_results) < 180),
            "safe": safe,
            "results": page_results,
        }


# Module-level singleton
search_engine = SearchEngine()
