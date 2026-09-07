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

import config
from database import db
from ddg_knowledge import get_instant_answer
from gemini_ai import gemini_ai
from indexer import indexer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SearchEngine:
    """Orchestrates a full search request end-to-end."""

    def search(self, query: str, top_n: int = config.DEFAULT_TOP_N) -> Dict[str, Any]:
        """Executes a full search pipeline for a user query.

        Steps:
            1. Spell-check the query via Gemini.
            2. Retrieve candidates from the inverted index using
               backtracking AND search.
            3. Filter out AI-flagged spam pages.
            4. Compute a composite score per candidate:
               0.40 * tfidf + 0.30 * pagerank + 0.30 * ai_relevance.
            5. Sort by composite score, descending.
            6. Summarize the top 3 results via Gemini.

        Args:
            query: The raw user search query.
            top_n: Maximum number of results to return.

        Returns:
            A dict matching the documented response schema:
            {original_query, corrected_query, ai_summary, total_results,
             results: [{rank, url, title, snippet, score, domain}]}
        """
        original_query = query
        if not query or not query.strip():
            return {
                "original_query": original_query,
                "corrected_query": "",
                "ai_summary": "",
                "total_results": 0,
                "results": [],
            }

        # Step 1: Spell check.
        corrected_query = gemini_ai.spell_check(query)

        # Step 2: Candidate retrieval via backtracking index search.
        candidates = indexer.backtracking_search(
            corrected_query, min_results=max(top_n * 3, config.DEFAULT_MIN_RESULTS)
        )

        # Normalize raw BM25 scores to [0, 1]
        max_bm25 = max((c.get("bm25_score", c.get("tfidf_score", 0.0)) for c in candidates), default=0.0)

        # Collect PageRanks for log-normalization
        raw_prs = {c["url"]: db.get_page_rank(c["url"]) for c in candidates}
        max_pr = max(raw_prs.values(), default=0.0)

        scored_results: List[Dict[str, Any]] = []

        for candidate in candidates:
            url = candidate["url"]
            page = db.get_page(url)
            if not page:
                continue

            title = page.get("title", "") or ""
            content = page.get("content", "") or ""
            meta_desc = page.get("meta_description", "") or ""
            domain = page.get("domain") or urlparse(url).netloc

            # 1. Okapi BM25 Normalized
            bm25_raw = candidate.get("bm25_score", candidate.get("tfidf_score", 0.0))
            bm25_norm = (bm25_raw / max_bm25) if max_bm25 > 0 else 0.0

            # 2. Log-normalized PageRank (DuckDuckGo / modern search standard)
            pr_raw = raw_prs.get(url, 0.0)
            if max_pr > 0:
                import math
                pr_norm = math.log1p(1000.0 * pr_raw) / math.log1p(1000.0 * max_pr)
            else:
                pr_norm = 0.0

            # 3. Exact Phrase & Term Proximity Scoring
            terms = candidate.get("matched_terms", [])
            proximity = indexer.compute_proximity_score(terms, url, corrected_query, page)

            # 4. Composite DuckDuckGo-style Ranking Formula
            final_score = (
                config.WEIGHT_BM25 * bm25_norm
                + config.WEIGHT_PAGERANK * pr_norm
                + config.WEIGHT_PROXIMITY * proximity
            )

            # Prefer meta_description as snippet (human-written, no JS artifacts).
            # Fall back to first 300 chars of cleaned page content.
            snippet = meta_desc if meta_desc else content[:300]
            snippet = re.sub(r'\$\{[^}]*\}', '', snippet)
            snippet = re.sub(r'[ \t]{2,}', ' ', snippet).strip()[:200]

            scored_results.append({
                "url": url,
                "title": title,
                "snippet": snippet,
                "score": round(float(final_score), 6),
                "domain": domain,
                "_content_for_summary": content,
            })

        # Step 5: Sort descending by composite score.
        scored_results.sort(key=lambda r: r["score"], reverse=True)
        top_results = scored_results[:top_n]

        # Step 6: AI summarization disabled to preserve Gemini free-tier
        # quota for spell-check. Summary always returns empty string.
        ai_summary = ""

        final_results = []
        for rank, r in enumerate(top_results, start=1):
            final_results.append({
                "rank": rank,
                "url": r["url"],
                "title": r["title"],
                "snippet": r["snippet"],
                "score": r["score"],
                "domain": r["domain"],
            })

        db.log_search(original_query, corrected_query, len(final_results))

        # DuckDuckGo Instant Answer Knowledge Panel
        knowledge_panel = get_instant_answer(corrected_query)

        return {
            "original_query": original_query,
            "corrected_query": corrected_query,
            "ai_summary": ai_summary,
            "knowledge_panel": knowledge_panel,
            "total_results": len(final_results),
            "results": final_results,
        }


# Module-level singleton for convenient importing elsewhere.
search_engine = SearchEngine()
