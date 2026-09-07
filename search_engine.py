"""
search_engine.py
=================
Top-level query orchestration: spell-checking, candidate retrieval via
the inverted index, AI-based spam filtering, composite scoring
(TF-IDF + PageRank + AI relevance), and result summarization.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List
from urllib.parse import urlparse

from ddgs import DDGS
import config
from database import db
from ddg_knowledge import get_instant_answer
from gemini_ai import gemini_ai
from indexer import indexer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SearchEngine:
    """Orchestrates live web search, spelling correction, and knowledge graphs."""

    def search(self, query: str, top_n: int = config.DEFAULT_TOP_N) -> Dict[str, Any]:
        """Executes a full live web search pipeline for a user query.

        Steps:
            1. Spell-check the query via Gemini Flash.
            2. Fetch live web search results across the entire internet via DDGS.
            3. Retrieve DuckDuckGo Knowledge Panel and entity pivot nodes.
            4. If offline, gracefully falls back to local inverted index.

        Args:
            query: The raw user search query.
            top_n: Maximum number of results to return.

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

        # Step 1: Spell check with Gemini Flash.
        corrected_query = gemini_ai.spell_check(query)

        # Step 2: Live web search across the entire internet (zero crawler/db needed).
        scored_results: List[Dict[str, Any]] = []
        try:
            raw_ddg = list(DDGS().text(corrected_query, max_results=top_n))
            for rank, r in enumerate(raw_ddg, start=1):
                url = r.get("href", "")
                domain = urlparse(url).netloc.replace("www.", "")
                scored_results.append({
                    "rank": rank,
                    "url": url,
                    "title": r.get("title", ""),
                    "snippet": r.get("body", ""),
                    "domain": domain,
                    "score": round(1.0 - (rank * 0.03), 3),
                })
        except Exception as exc:
            logger.warning("Live web search error: %s; attempting local index fallback", exc)

        # Step 3: Local fallback if live search returned empty
        if not scored_results:
            candidates = indexer.backtracking_search(
                corrected_query, min_results=max(top_n, 5)
            )
            for rank, c in enumerate(candidates[:top_n], start=1):
                url = c["url"]
                page = db.get_page(url) or {}
                domain = page.get("domain") or urlparse(url).netloc.replace("www.", "")
                snippet = page.get("meta_description") or page.get("content", "")[:200]
                snippet = re.sub(r'\$\{[^}]*\}', '', snippet).strip()
                scored_results.append({
                    "rank": rank,
                    "url": url,
                    "title": page.get("title") or url,
                    "snippet": snippet,
                    "domain": domain,
                    "score": round(float(c.get("bm25_score", 0.5)), 3),
                })

        final_results = scored_results[:top_n]

        db.log_search(original_query, corrected_query, len(final_results))

        # DuckDuckGo Instant Answer Knowledge Panel
        knowledge_panel = get_instant_answer(corrected_query)

        return {
            "original_query": original_query,
            "corrected_query": corrected_query,
            "ai_summary": "",
            "knowledge_panel": knowledge_panel,
            "total_results": len(final_results),
            "results": final_results,
        }


# Module-level singleton for convenient importing elsewhere.
search_engine = SearchEngine()
