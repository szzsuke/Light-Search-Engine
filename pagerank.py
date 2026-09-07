"""
pagerank.py
===========
Iterative PageRank implementation over the crawled page graph.

Implements the classic formula:

    PR(A) = (1 - d) / N + d * sum(PR(Ti) / C(Ti) for Ti in incoming(A))

where `d` is the damping factor, `N` is the total number of unique pages
in the corpus, `Ti` ranges over pages linking to `A`, and `C(Ti)` is the
total number of outbound links (internal + external) from `Ti`.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Set
from urllib.parse import urlparse

import numpy as np

import config
from database import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PageRankEngine:
    """Computes and persists PageRank scores for the crawled corpus."""

    def __init__(
        self,
        damping: float = config.PAGERANK_DAMPING,
        threshold: float = config.PAGERANK_CONVERGENCE_THRESHOLD,
        max_iterations: int = config.PAGERANK_MAX_ITERATIONS,
    ) -> None:
        """Initializes the PageRank engine.

        Args:
            damping: The damping factor `d` (typically 0.85).
            threshold: Convergence threshold on the maximum score delta
                between iterations.
            max_iterations: Safety cap on iteration count in case the
                graph never converges below `threshold`.
        """
        self.damping = damping
        self.threshold = threshold
        self.max_iterations = max_iterations

    def build_graph(self) -> tuple:
        """Builds the link graph from `raw_pages`.

        Only edges pointing to another URL that exists in the crawled
        corpus are counted as incoming edges (i.e. contribute to a page's
        PageRank). All outbound links found on a page -- whether or not
        their target was crawled -- count toward that page's outbound
        link count C(Ti), per the standard formula.

        Returns:
            A tuple of:
                urls: List[str] of all crawled page URLs (index -> url).
                incoming: Dict[str, List[str]] mapping a URL to the list
                    of in-corpus URLs that link to it.
                outdegree: Dict[str, int] mapping a URL to its total
                    outbound link count (all links found on that page).
        """
        urls: List[str] = []
        outdegree: Dict[str, int] = {}
        outlinks: Dict[str, List[str]] = {}

        for page in db.all_pages(projection={"url": 1, "links": 1}):
            url = page.get("url")
            if not url:
                continue
            links = page.get("links") or []
            urls.append(url)
            outdegree[url] = len(links)
            outlinks[url] = links

        url_set: Set[str] = set(urls)
        incoming: Dict[str, List[str]] = {u: [] for u in urls}

        for src, links in outlinks.items():
            for dst in links:
                if dst in url_set and dst != src:
                    incoming[dst].append(src)

        return urls, incoming, outdegree

    def compute(self) -> Dict[str, float]:
        """Runs the iterative PageRank algorithm to convergence.

        Returns:
            Dict mapping each URL to its normalized PageRank score in
            the range [0, 1]. Returns an empty dict if the corpus is
            empty.
        """
        urls, incoming, outdegree = self.build_graph()
        n = len(urls)
        if n == 0:
            logger.warning("No pages found in raw_pages; skipping PageRank.")
            return {}

        url_index = {url: i for i, url in enumerate(urls)}
        scores = np.full(n, 1.0 / n, dtype=np.float64)

        base = (1.0 - self.damping) / n

        for iteration in range(1, self.max_iterations + 1):
            new_scores = np.full(n, base, dtype=np.float64)

            for url in urls:
                idx = url_index[url]
                contribution = 0.0
                for src in incoming.get(url, []):
                    c_ti = outdegree.get(src, 0)
                    if c_ti > 0:
                        contribution += scores[url_index[src]] / c_ti
                new_scores[idx] += self.damping * contribution

            max_delta = float(np.max(np.abs(new_scores - scores)))
            scores = new_scores

            if max_delta < self.threshold:
                logger.info(
                    "PageRank converged after %d iterations (max_delta=%.6f).",
                    iteration, max_delta,
                )
                break
        else:
            logger.info(
                "PageRank reached max_iterations=%d without full convergence.",
                self.max_iterations,
            )

        # Normalize to [0, 1].
        min_score = float(np.min(scores))
        max_score = float(np.max(scores))
        score_range = max_score - min_score
        if score_range > 0:
            normalized = (scores - min_score) / score_range
        else:
            normalized = np.zeros_like(scores)

        return {url: float(normalized[url_index[url]]) for url in urls}

    def compute_and_store(self) -> int:
        """Computes PageRank scores and persists them to MongoDB.

        Returns:
            The number of URLs scored and stored.
        """
        scores = self.compute()
        if not scores:
            return 0

        db.clear_page_rank()
        count = 0
        for url, score in scores.items():
            domain = urlparse(url).netloc
            if db.upsert_page_rank(url, score, domain):
                count += 1

        logger.info("Stored PageRank scores for %d pages.", count)
        return count


# Module-level singleton.
pagerank_engine = PageRankEngine()


if __name__ == "__main__":
    pagerank_engine.compute_and_store()
