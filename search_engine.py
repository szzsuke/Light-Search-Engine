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

    def search(self, query: str, top_n: int = config.DEFAULT_TOP_N, mode: str = "all") -> Dict[str, Any]:
        """Executes a full live web search pipeline for a user query.

        Steps:
            1. Spell-check query via Gemini Flash.
            2. Dual-channel retrieval: fetches live web results + community discussions.
            3. Smart Reranker: boosts authentic human discussions (Reddit, GitHub, HN),
               evaluates title-match relevance, and penalizes SEO spam.
            4. Retrieves DuckDuckGo Knowledge Panel.
            5. Gracefully falls back to local index if offline.

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

        # Step 1: Spell check with Gemini Flash.
        corrected_query = gemini_ai.spell_check(query)

        # Step 2: Dual-Channel Live Web & Community Retrieval
        raw_candidates: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()

        query_tokens = [w.lower() for w in re.findall(r"\b[a-z0-9]+\b", corrected_query) if len(w) > 2]

        try:
            if mode == "discussions":
                # Pure human community mode
                search_q = f"{corrected_query} (site:reddit.com OR site:news.ycombinator.com OR site:github.com OR site:stackoverflow.com)"
                raw_ddg = list(DDGS().text(search_q, max_results=top_n + 5))
                for r in raw_ddg:
                    u = r.get("href", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        raw_candidates.append(r)
            else:
                # Mode == 'all': Dual-channel blend (General Web + Top Reddit Discussions)
                web_results = list(DDGS().text(corrected_query, max_results=top_n + 5))
                for r in web_results:
                    u = r.get("href", "")
                    if u and u not in seen_urls:
                        seen_urls.add(u)
                        raw_candidates.append(r)

                # Fetch authentic Reddit discussions
                try:
                    reddit_results = list(DDGS().text(f"{corrected_query} site:reddit.com", max_results=4))
                    for r in reddit_results:
                        u = r.get("href", "")
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            raw_candidates.append(r)
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("Live web search error: %s; attempting local index fallback", exc)

        # Step 3: Smart Reranker: Title Relevance + Community Factor + Spam Demotion
        scored_results: List[Dict[str, Any]] = []

        if raw_candidates:
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

        # Step 4: Local fallback if live search returned empty
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
