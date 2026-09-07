"""
search_engine.py
=================
SOUL Search Engine Core Orchestrator:
- Ultra-fast concurrent multi-engine retrieval (DuckDuckGo + Brave fast backends).
- Brave/Bing-quality ranking with strict Domain Diversity (Host Collapsing).
- Eliminates Wikipedia duplicates/flooding (max 1 Wikipedia per query).
- Natural organic blending of authentic community discussions (Reddit/GitHub).
- DuckDuckGo Instant Answer / Knowledge Graph integration.
- In-memory fast LRU/TTL cache for instant repeated searches.
- 100% standalone — zero crawler or local database needed.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from ddgs import DDGS

import config
from ddg_knowledge import get_instant_answer
from gemini_ai import gemini_ai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Shared persistent thread pool for low-latency concurrent retrieval
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="soul_search")

# In-memory query result cache: (query_norm, mode, top_n) -> (timestamp, result_dict)
_QUERY_CACHE: Dict[Tuple[str, str, int], Tuple[float, Dict[str, Any]]] = {}
_CACHE_TTL_SECONDS = 900  # 15 minutes cache lifetime
_MAX_CACHE_ENTRIES = 512

# Low-quality SEO affiliate / spam domains to filter or demote
_BLOCKED_DOMAINS = {
    "pinterest.com",
    "bestproducts.com",
    "toptenreviews.com",
}


def _get_from_cache(query: str, mode: str, top_n: int) -> Dict[str, Any] | None:
    key = (query.strip().lower(), mode, top_n)
    if key in _QUERY_CACHE:
        ts, data = _QUERY_CACHE[key]
        if time.time() - ts < _CACHE_TTL_SECONDS:
            logger.info("Cache hit for query: '%s' [%s]", query, mode)
            return data
        else:
            del _QUERY_CACHE[key]
    return None


def _put_in_cache(query: str, mode: str, top_n: int, data: Dict[str, Any]) -> None:
    if len(_QUERY_CACHE) >= _MAX_CACHE_ENTRIES:
        oldest_keys = sorted(_QUERY_CACHE.keys(), key=lambda k: _QUERY_CACHE[k][0])[:100]
        for k in oldest_keys:
            _QUERY_CACHE.pop(k, None)
    key = (query.strip().lower(), mode, top_n)
    _QUERY_CACHE[key] = (time.time(), data)


def get_root_domain(url: str) -> str:
    """Extracts root domain for host collapsing and domain diversity.

    Ensures subdomains (en.wikipedia.org, simple.wikipedia.org, hi.wikipedia.org)
    all map to 'wikipedia.org' to prevent single-domain result flooding.
    """
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


def _safe_ddgs_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Fetches web results using direct fast backends (DuckDuckGo, Brave, Yahoo, Startpage) with fallback."""
    try:
        results = list(DDGS(timeout=5).text(query, backend="duckduckgo,brave,yahoo,startpage", max_results=max_results))
        if results:
            return results
    except Exception as exc:
        logger.warning("Fast backend search error for '%s': %s", query, exc)

    try:
        return list(DDGS(timeout=4).text(query, max_results=max_results))
    except Exception as exc:
        logger.warning("Fallback DDGS search error for '%s': %s", query, exc)
        return []


class SearchEngine:
    """Orchestrates live web search with Brave/Bing-quality domain diversity and ranking."""

    def search(self, query: str, top_n: int = config.DEFAULT_TOP_N, mode: str = "all") -> Dict[str, Any]:
        """Executes a live search pipeline preserving native ranking quality with host collapsing.

        Key Ranking Principles:
            1. Host Collapsing / Domain Diversity: Strict cap of 1 result per root domain
               (no more 3-4 Wikipedia mirrors taking up all top spots).
            2. Brave / DuckDuckGo Native Relevance: Preserves high-relevance algorithmic
               ordering instead of crude artificial boosts.
            3. Organic Community Blending: Weaves top authentic discussions (Reddit, GitHub)
               into the result stream naturally without hijacking official sites.
            4. Instant DuckDuckGo Knowledge Card & Non-blocking Spell Check.
        """
        original_query = query
        if not query or not query.strip():
            return {
                "original_query": original_query,
                "corrected_query": "",
                "ai_summary": "",
                "knowledge_panel": None,
                "total_results": 0,
                "results": [],
            }

        # Check Cache
        cached = _get_from_cache(original_query, mode, top_n)
        if cached:
            return cached

        # Step 1: Concurrently dispatch search tasks
        fut_kp = _EXECUTOR.submit(get_instant_answer, original_query)
        fut_spell = _EXECUTOR.submit(gemini_ai.spell_check, original_query)

        fut_web = _EXECUTOR.submit(_safe_ddgs_search, original_query, top_n + 10)
        fut_reddit = _EXECUTOR.submit(_safe_ddgs_search, f"{original_query} site:reddit.com", 4)

        # Collect raw web results
        web_results: List[Dict[str, Any]] = []
        try:
            web_results = fut_web.result(timeout=5.0)
        except Exception as exc:
            logger.warning("Web retrieval error: %s", exc)

        # Collect Reddit community results
        reddit_results: List[Dict[str, Any]] = []
        try:
            reddit_results = fut_reddit.result(timeout=5.0)
        except Exception as exc:
            logger.warning("Reddit retrieval error: %s", exc)

        # Step 2: Resolve Knowledge Panel & Spell Check (non-blocking)
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

        # Step 3: Domain Diversity & Intelligent Blending (Host Collapsing)
        is_reddit_query = "reddit" in original_query.lower()
        max_reddit_allowed = 10 if is_reddit_query else 2
        max_wiki_allowed = 1  # Never allow more than 1 Wikipedia page to monopolize results

        domain_counts: Dict[str, int] = {}
        seen_urls: set[str] = set()
        blended_results: List[Dict[str, Any]] = []

        # Prepare filtered Reddit candidates
        clean_reddit = []
        for r in reddit_results:
            u = r.get("href", "")
            if u and "reddit.com" in u and u not in seen_urls:
                clean_reddit.append(r)

        reddit_inserted = 0
        web_inserted = 0

        # Pass 1: Strict Domain Diversity (Max 1 per root domain, natural Reddit injection)
        for r in web_results:
            url = r.get("href", "")
            if not url or url in seen_urls:
                continue

            root_dom = get_root_domain(url)
            display_dom = urlparse(url).netloc.replace("www.", "").lower()

            # Filter known affiliate spam
            if any(spam in root_dom for spam in _BLOCKED_DOMAINS):
                continue

            # Check domain caps
            current_count = domain_counts.get(root_dom, 0)
            if root_dom == "wikipedia.org" and current_count >= max_wiki_allowed:
                continue
            if root_dom == "reddit.com" and current_count >= max_reddit_allowed:
                continue
            if current_count >= 1:
                continue

            seen_urls.add(url)
            domain_counts[root_dom] = current_count + 1
            blended_results.append({
                "url": url,
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "domain": display_dom,
            })
            web_inserted += 1

            # After top 2 authoritative web results, blend 1 top relevant Reddit discussion (if available)
            if web_inserted == 2 and clean_reddit and reddit_inserted == 0:
                for red in clean_reddit:
                    r_url = red.get("href", "")
                    if r_url and r_url not in seen_urls and domain_counts.get("reddit.com", 0) < max_reddit_allowed:
                        seen_urls.add(r_url)
                        domain_counts["reddit.com"] = domain_counts.get("reddit.com", 0) + 1
                        blended_results.append({
                            "url": r_url,
                            "title": red.get("title", ""),
                            "snippet": red.get("body", ""),
                            "domain": "reddit.com",
                        })
                        reddit_inserted += 1
                        break

        # Pass 2: If we still need more results to fulfill top_n, allow a 2nd result from established domains (excluding wikipedia)
        if len(blended_results) < top_n:
            for r in web_results:
                if len(blended_results) >= top_n:
                    break
                url = r.get("href", "")
                if not url or url in seen_urls:
                    continue
                root_dom = get_root_domain(url)
                display_dom = urlparse(url).netloc.replace("www.", "").lower()
                if root_dom == "wikipedia.org":  # Never duplicate wikipedia
                    continue
                if any(spam in root_dom for spam in _BLOCKED_DOMAINS):
                    continue
                if domain_counts.get(root_dom, 0) < 2:
                    seen_urls.add(url)
                    domain_counts[root_dom] = domain_counts.get(root_dom, 0) + 1
                    blended_results.append({
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "domain": display_dom,
                    })

        # Assign final clean ranks
        final_results = blended_results[:top_n]
        for rank, item in enumerate(final_results, start=1):
            item["rank"] = rank

        result_payload = {
            "original_query": original_query,
            "corrected_query": corrected_query,
            "ai_summary": "",
            "knowledge_panel": knowledge_panel,
            "total_results": len(final_results),
            "results": final_results,
        }

        if final_results:
            _put_in_cache(original_query, mode, top_n, result_payload)

        return result_payload


# Module-level singleton for convenient importing elsewhere.
search_engine = SearchEngine()
