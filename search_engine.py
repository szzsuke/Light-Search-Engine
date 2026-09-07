"""
search_engine.py
=================
SOUL Search Engine Core Orchestrator:
- Ultra-fast concurrent multi-engine retrieval (DuckDuckGo + Brave fast backends).
- Parallel Knowledge Graph (DuckDuckGo Instant Answer) & AI Spell Checking.
- Smart Relevance & Community Reranker (+45% authentic discussion boost, title-match bonus).
- In-memory fast LRU cache for instant repeated search delivery.
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
        # Evict oldest 20%
        oldest_keys = sorted(_QUERY_CACHE.keys(), key=lambda k: _QUERY_CACHE[k][0])[:100]
        for k in oldest_keys:
            _QUERY_CACHE.pop(k, None)
    key = (query.strip().lower(), mode, top_n)
    _QUERY_CACHE[key] = (time.time(), data)


def _safe_ddgs_search(query: str, max_results: int) -> List[Dict[str, Any]]:
    """Fetches web results using direct fast backends (DuckDuckGo + Brave) with fallback."""
    try:
        # Direct fast backends bypass rate-limited engine cascades
        results = list(DDGS(timeout=4).text(query, backend="duckduckgo,brave", max_results=max_results))
        if results:
            return results
    except Exception as exc:
        logger.warning("Fast backend search error for '%s': %s", query, exc)

    # Fallback to standard auto-backend if specific backends fail
    try:
        return list(DDGS(timeout=4).text(query, max_results=max_results))
    except Exception as exc:
        logger.warning("Fallback DDGS search error for '%s': %s", query, exc)
        return []


class SearchEngine:
    """Orchestrates live web search, spelling correction, and knowledge graphs with concurrent retrieval."""

    def search(self, query: str, top_n: int = config.DEFAULT_TOP_N, mode: str = "all") -> Dict[str, Any]:
        """Executes an ultra-fast live web search pipeline for a user query.

        Steps:
            1. Check in-memory result cache.
            2. Concurrently dispatch:
               - Web search (DuckDuckGo + Brave fast backends)
               - Reddit/community discussions search
               - Knowledge Graph (Instant Answer)
               - AI Spell check (Gemini Flash with fast-path timeout)
            3. Smart Reranker: boosts authentic human discussions (Reddit, GitHub, HN),
               evaluates title-match relevance, and penalizes SEO spam.
            4. Returns blended, ranked results + knowledge panel.

        Args:
            query: The raw user search query.
            top_n: Maximum number of results to return.
            mode: Search mode ('all' for smart blend, 'discussions' for Reddit/forums only).

        Returns:
            Dict containing results, knowledge_panel, and query metadata.
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
        # - Knowledge Graph task
        fut_kp = _EXECUTOR.submit(get_instant_answer, original_query)

        # - AI Spell check task (runs in background with fast timeout)
        fut_spell = _EXECUTOR.submit(gemini_ai.spell_check, original_query)

        # - Web & Community retrieval tasks
        raw_candidates: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()

        if mode == "discussions":
            search_q = f"{original_query} (site:reddit.com OR site:news.ycombinator.com OR site:github.com OR site:stackoverflow.com)"
            fut_disc = _EXECUTOR.submit(_safe_ddgs_search, search_q, top_n + 5)
            try:
                for r in fut_disc.result(timeout=5.0):
                    u = r.get("href", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        raw_candidates.append(r)
            except Exception as exc:
                logger.warning("Discussions retrieval error: %s", exc)
        else:
            # Mode == 'all': Parallel Dual-channel blend (General Web + Top Reddit Discussions)
            fut_web = _EXECUTOR.submit(_safe_ddgs_search, original_query, top_n + 5)
            fut_reddit = _EXECUTOR.submit(_safe_ddgs_search, f"{original_query} site:reddit.com", 4)

            try:
                for r in fut_web.result(timeout=5.0):
                    u = r.get("href", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        raw_candidates.append(r)
            except Exception as exc:
                logger.warning("Web retrieval error: %s", exc)

            try:
                for r in fut_reddit.result(timeout=5.0):
                    u = r.get("href", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        raw_candidates.append(r)
            except Exception as exc:
                logger.warning("Reddit retrieval error: %s", exc)

        # Step 2: Resolve Knowledge Panel (non-blocking if finished)
        knowledge_panel = None
        try:
            knowledge_panel = fut_kp.result(timeout=1.5)
        except Exception as exc:
            logger.debug("Knowledge panel retrieval timeout or error: %s", exc)

        # Step 3: Resolve Spell Check (non-blocking if finished within 0.8s)
        corrected_query = original_query
        try:
            corrected_query = fut_spell.result(timeout=0.8)
        except (TimeoutError, Exception):
            # Do not block the user if Gemini is slow
            corrected_query = original_query

        # Step 4: Smart Reranker: Title Relevance + Community Factor + Spam Demotion
        query_tokens = [w.lower() for w in re.findall(r"\b[a-z0-9]+\b", original_query) if len(w) > 2]
        scored_results: List[Dict[str, Any]] = []

        for rank_idx, r in enumerate(raw_candidates, start=1):
            url = r.get("href", "")
            domain = urlparse(url).netloc.replace("www.", "").lower()
            title = r.get("title", "")
            title_lower = title.lower()
            snippet = r.get("body", "")

            base_score = 1.0 - (rank_idx * 0.02)

            # 1. Authentic Human Community Multiplier (+45% boost)
            domain_multiplier = 1.0
            if any(d in domain for d in ("reddit.com", "news.ycombinator.com", "stackoverflow.com", "github.com")):
                domain_multiplier = 1.45
            elif any(d in domain for d in ("wikipedia.org", "arxiv.org", "nature.com", "mit.edu", "stanford.edu")):
                domain_multiplier = 1.30
            elif any(d in domain for d in ("forum", "community", "stackexchange.com", "quora.com", "medium.com")):
                domain_multiplier = 1.15
            elif any(d in domain for d in ("pinterest.com", "forbes.com/advisor", "bestproducts.com")):
                domain_multiplier = 0.50  # Demote SEO affiliate farms

            # 2. Query Term Match Density in Title
            matches = sum(1 for token in query_tokens if token in title_lower)
            title_bonus = (matches / len(query_tokens)) * 0.35 if query_tokens else 0.0

            composite_score = (base_score * domain_multiplier) + title_bonus

            scored_results.append({
                "url": url,
                "title": title,
                "snippet": snippet,
                "domain": domain,
                "score": round(composite_score, 3),
            })

        # Sort descending by composite score
        scored_results.sort(key=lambda x: x["score"], reverse=True)
        for new_rank, item in enumerate(scored_results, start=1):
            item["rank"] = new_rank

        final_results = scored_results[:top_n]

        result_payload = {
            "original_query": original_query,
            "corrected_query": corrected_query,
            "ai_summary": "",
            "knowledge_panel": knowledge_panel,
            "total_results": len(final_results),
            "results": final_results,
        }

        # Cache valid results
        if final_results:
            _put_in_cache(original_query, mode, top_n, result_payload)

        return result_payload


# Module-level singleton for convenient importing elsewhere.
search_engine = SearchEngine()
