"""
indexer.py
==========
Builds an inverted index from the `raw_pages` collection and provides
query-time retrieval via a backtracking AND-search algorithm plus a
standard TF-IDF scoring function.

Tokenization: lowercase, regex `\\b[a-z0-9]+\\b`, English stopwords removed.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from typing import Any, Dict, List, Tuple

import config
from database import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"\b[a-z0-9]+\b")


def tokenize(text: str) -> List[str]:
    """Tokenizes text into lowercase alphanumeric terms with stopwords removed.

    Args:
        text: Raw text to tokenize.

    Returns:
        List of tokens in order of appearance (stopwords excluded).
    """
    if not text:
        return []
    lowered = text.lower()
    tokens = _TOKEN_RE.findall(lowered)
    return [t for t in tokens if t not in config.STOPWORDS]


class Indexer:
    """Builds and queries the inverted index stored in MongoDB."""

    def build_index(self) -> int:
        """Rebuilds the entire inverted index from `raw_pages` with BM25 metadata.

        Iterates every crawled page, computes field-specific token counts
        (title, body, url), document lengths, and writes the resulting
        term -> postings mapping with BM25 stats into the `inverted_index`
        collection.

        Returns:
            The number of unique terms indexed.
        """
        logger.info("Starting inverted index build with BM25 & field weights...")
        term_postings: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

        total_docs = 0
        total_tokens = 0

        for page in db.all_pages(projection={"url": 1, "content": 1, "title": 1, "domain": 1}):
            url = page.get("url")
            if not url:
                continue

            title_tokens = tokenize(page.get("title", ""))
            content_tokens = tokenize(page.get("content", ""))
            url_tokens = tokenize(url)

            # Combined token stream for position tracking
            combined_tokens = title_tokens + content_tokens
            doc_len = len(combined_tokens)
            if doc_len == 0:
                continue

            total_docs += 1
            total_tokens += doc_len

            from collections import Counter
            title_counts = Counter(title_tokens)
            url_counts = Counter(url_tokens)

            positions: Dict[str, List[int]] = defaultdict(list)
            for pos, tok in enumerate(combined_tokens):
                positions[tok].append(pos)

            for term, pos_list in positions.items():
                term_postings[term].append({
                    "url": url,
                    "tf": len(pos_list),
                    "title_tf": title_counts.get(term, 0),
                    "url_tf": url_counts.get(term, 0),
                    "doc_len": doc_len,
                    "positions": pos_list,
                })

        db.clear_index()
        for term, postings in term_postings.items():
            db.upsert_term_postings(term, postings)

        avg_doc_len = (total_tokens / max(total_docs, 1))
        db.set_index_meta({
            "avg_doc_len": avg_doc_len,
            "total_docs": total_docs,
            "total_terms": len(term_postings),
        })

        logger.info(
            "Index build complete. %d documents, %d unique terms, avg_doc_len: %.1f.",
            total_docs, len(term_postings), avg_doc_len,
        )
        return len(term_postings)

    def document_frequency(self, term: str) -> int:
        """Returns the number of documents containing `term`."""
        doc = db.get_postings(term)
        if not doc:
            return 0
        return len(doc.get("postings", []))

    def total_documents(self) -> int:
        """Returns the total number of crawled documents."""
        meta = db.get_index_meta()
        if meta and "total_docs" in meta:
            return meta["total_docs"]
        return max(db.count_pages(), 1)

    def average_document_length(self) -> float:
        """Returns the average document length across the collection."""
        meta = db.get_index_meta()
        if meta and "avg_doc_len" in meta:
            return float(meta["avg_doc_len"])
        return 350.0  # standard fallback if index has not yet run

    def compute_bm25(self, term: str, url: str) -> float:
        """Computes the field-weighted Okapi BM25 score for a term/document pair.

        Uses Robertson-Spärck Jones IDF with document length normalization and
        title/URL field weighting (inspired by DuckDuckGo and Lucene BM25F).
        """
        doc = db.get_postings(term)
        if not doc:
            return 0.0

        postings = doc.get("postings", [])
        df = len(postings)
        if df == 0:
            return 0.0

        target_posting = None
        for p in postings:
            if p.get("url") == url:
                target_posting = p
                break

        if not target_posting:
            return 0.0

        # Term frequency breakdown
        raw_tf = target_posting.get("tf", 0)
        title_tf = target_posting.get("title_tf", 0)
        url_tf = target_posting.get("url_tf", 0)
        doc_len = target_posting.get("doc_len", 350)
        avg_doc_len = self.average_document_length()

        # Field-weighted TF: Title matches receive a 4x boost, URL 3x boost
        body_tf = max(0, raw_tf - title_tf)
        weighted_tf = (
            title_tf * config.BM25_TITLE_WEIGHT
            + url_tf * config.BM25_URL_WEIGHT
            + body_tf * 1.0
        )

        if weighted_tf <= 0:
            return 0.0

        # Robertson-Spärck Jones IDF
        n = self.total_documents()
        idf = math.log(((n - df + 0.5) / (df + 0.5)) + 1.0)
        idf = max(idf, 0.001)

        # Okapi BM25 with length normalization
        k1 = config.BM25_K1
        b = config.BM25_B
        len_norm = 1.0 - b + b * (doc_len / max(avg_doc_len, 1.0))
        bm25 = idf * ((weighted_tf * (k1 + 1.0)) / (weighted_tf + k1 * len_norm))

        return float(bm25)

    def compute_tfidf(self, term: str, url: str) -> float:
        """Legacy TF-IDF score for compatibility; maps to BM25."""
        return self.compute_bm25(term, url)

    def compute_proximity_score(self, terms: List[str], url: str, query: str, page_doc: Dict[str, Any]) -> float:
        """Computes phrase proximity and exact title matching bonus."""
        if not terms or not page_doc:
            return 0.0

        q_lower = query.strip().lower()
        title = (page_doc.get("title") or "").lower()
        content = (page_doc.get("content") or "").lower()

        score = 0.0
        # 1. Exact query phrase in title (massive boost)
        if q_lower in title:
            score += 0.65
        # 2. Exact query phrase in body
        elif q_lower in content:
            score += 0.35

        # 3. Term proximity in postings
        if len(terms) > 1:
            try:
                # Find all positions for each term
                postings_positions = []
                for t in terms:
                    doc = db.get_postings(t)
                    if doc:
                        for p in doc.get("postings", []):
                            if p.get("url") == url:
                                postings_positions.append(p.get("positions", []))
                                break
                if len(postings_positions) == len(terms):
                    # Check if terms occur within a narrow span
                    all_pos = [pos for sublist in postings_positions for pos in sublist]
                    if all_pos and (max(all_pos) - min(all_pos)) < len(terms) * 4:
                        score += 0.20
            except Exception:
                pass

        return min(1.0, score)

    def backtracking_search(
        self, query: str, min_results: int = config.DEFAULT_MIN_RESULTS
    ) -> List[Dict[str, Any]]:
        """Finds documents matching query terms using BM25 ranking and backtracking relaxation."""
        terms = tokenize(query)
        if not terms:
            return []
        return self._backtrack(terms, min_results)

    def _backtrack(self, terms: List[str], min_results: int) -> List[Dict[str, Any]]:
        """Recursive helper implementing the backtracking relaxation logic."""
        if not terms:
            return []

        matches = self._and_search(terms)

        if len(matches) >= min_results or len(terms) == 1:
            return matches

        # Identify the rarest term (lowest document frequency) and drop it.
        dfs = [(t, self.document_frequency(t)) for t in terms]
        dfs.sort(key=lambda pair: pair[1])
        rarest_term = dfs[0][0]
        reduced_terms = [t for t in terms if t != rarest_term]

        relaxed_matches = self._backtrack(reduced_terms, min_results)

        seen_urls = {m["url"] for m in matches}
        merged = matches + [m for m in relaxed_matches if m["url"] not in seen_urls]
        return merged

    def _and_search(self, terms: List[str]) -> List[Dict[str, Any]]:
        """Performs an AND search: documents containing every given term scored by BM25."""
        if not terms:
            return []

        postings_by_term: Dict[str, Dict[str, Any]] = {}
        for term in terms:
            doc = db.get_postings(term)
            if not doc or not doc.get("postings"):
                return []
            postings_by_term[term] = {p["url"]: p for p in doc["postings"]}

        # Intersect URL sets across all terms.
        url_sets = [set(postings.keys()) for postings in postings_by_term.values()]
        common_urls = set.intersection(*url_sets) if url_sets else set()

        results: List[Dict[str, Any]] = []
        for url in common_urls:
            bm25_score = sum(self.compute_bm25(term, url) for term in terms)
            results.append({
                "url": url,
                "matched_terms": list(terms),
                "bm25_score": bm25_score,
                "tfidf_score": bm25_score,
            })

        results.sort(key=lambda r: r["bm25_score"], reverse=True)
        return results


# Module-level singleton for convenient importing elsewhere.
indexer = Indexer()
