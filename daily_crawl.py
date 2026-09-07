"""
daily_crawl.py
==============
Automated Daily Pipeline:
Crawls a configured batch of pages (default: 25,000 pages), then automatically
builds the inverted index with Okapi BM25 metadata and computes PageRank.

Can be run locally:
    python daily_crawl.py --pages 25000

Or automatically in GitHub Actions / cron:
    python daily_crawl.py
"""

from __future__ import annotations

import argparse
import datetime
import logging
import os
import random
import sys
import time
from collections import defaultdict
from urllib.parse import urlparse
from pymongo import MongoClient

import config
from crawler import Crawler, canonicalize_url
from indexer import indexer
from pagerank import pagerank_engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("daily_pipeline")


def get_expansion_seeds(needed_count: int, client: MongoClient) -> tuple[list[str], set[str]]:
    """Gathers fresh unvisited seed URLs across all web genres with domain diversity."""
    db = client[config.MONGO_DB_NAME]
    pages_col = db[config.COLLECTION_RAW_PAGES]

    logger.info("Reading visited URLs from database...")
    visited = set(doc["url"] for doc in pages_col.find({}, {"url": 1}))
    logger.info("Total visited pages in database: %d", len(visited))

    # 1. Primary multi-genre seeds from TARGET_SITES
    primary_seeds: list[str] = []
    for site in config.TARGET_SITES:
        canon = canonicalize_url(site)
        if canon not in visited:
            primary_seeds.append(canon)
    logger.info("Found %d unvisited primary multi-genre seeds.", len(primary_seeds))

    # 2. Extract discovered outlinks across the ENTIRE web, enforcing domain diversity
    max_candidates = max(needed_count * 2, 50000)
    discovered_seeds: list[str] = []
    domain_seed_counts: dict[str, int] = defaultdict(int)

    logger.info("Scanning existing outlinks across all genres on the web...")
    cursor = pages_col.find({}, {"links": 1}).batch_size(1000)

    for doc in cursor:
        links = doc.get("links", [])
        for link in links:
            if not link or not link.startswith(("http://", "https://")):
                continue
            parsed_domain = urlparse(link).netloc.lower().replace("www.", "")
            if not parsed_domain or "." not in parsed_domain:
                continue

            # Cap seeds per domain to 25 to guarantee wide diversity across hundreds of genres/sites
            if domain_seed_counts[parsed_domain] >= 25:
                continue

            canon = canonicalize_url(link)
            if canon not in visited:
                discovered_seeds.append(canon)
                domain_seed_counts[parsed_domain] += 1
                if len(discovered_seeds) >= max_candidates:
                    break
        if len(discovered_seeds) >= max_candidates:
            break

    # Shuffle seeds so workers hit multiple different domains/genres simultaneously
    random.shuffle(discovered_seeds)
    logger.info(
        "Gathered %d candidate expansion seeds across %d distinct domains and genres.",
        len(discovered_seeds),
        len(domain_seed_counts),
    )
    combined_seeds = primary_seeds + discovered_seeds
    return combined_seeds, visited


def run_daily_pipeline(pages_to_crawl: int = 25000, skip_indexing: bool = False) -> dict:
    """Executes the daily crawl, indexing, and ranking pipeline.

    Args:
        pages_to_crawl: Number of new pages to crawl in this run (default: 25,000).
        skip_indexing: If True, skips building index and PageRank.

    Returns:
        A dictionary containing execution statistics.
    """
    start_time = time.time()
    logger.info("==========================================================")
    logger.info("STARTING AUTOMATED DAILY PIPELINE (Target: %d pages)", pages_to_crawl)
    logger.info("Timestamp: %s", datetime.datetime.now(datetime.timezone.utc).isoformat())
    logger.info("MongoDB URI: %s | DB: %s", config.MONGO_URI, config.MONGO_DB_NAME)
    logger.info("==========================================================")

    client = MongoClient(config.MONGO_URI)
    initial_count = client[config.MONGO_DB_NAME][config.COLLECTION_RAW_PAGES].count_documents({})
    logger.info("Initial document count: %d", initial_count)

    # Phase 1: Seed discovery
    seeds, visited = get_expansion_seeds(pages_to_crawl, client)
    client.close()

    if not seeds:
        logger.warning("No new expansion seeds available! Resetting or using default target sites.")
        seeds = [canonicalize_url(s) for s in config.TARGET_SITES]

    # Phase 2: Web Crawling
    logger.info("Phase 1/3: Starting Crawler (workers: %d, max_pages: %d)...", config.MAX_WORKERS, pages_to_crawl)
    crawler = Crawler(max_pages=pages_to_crawl)
    crawler.visited = visited
    new_pages_crawled = crawler.run(seed_urls=seeds)
    crawl_duration = time.time() - start_time
    logger.info("Crawl completed in %.1f seconds. New pages added: %d", crawl_duration, new_pages_crawled)

    # Verify updated database count
    client = MongoClient(config.MONGO_URI)
    final_page_count = client[config.MONGO_DB_NAME][config.COLLECTION_RAW_PAGES].count_documents({})
    client.close()
    logger.info("Total documents in database after crawl: %d", final_page_count)

    indexed_terms = 0
    pagerank_pages = 0
    index_duration = 0.0

    # Phase 3: Indexing & Ranking
    if not skip_indexing:
        index_start = time.time()
        logger.info("Phase 2/3: Building Okapi BM25 Inverted Index...")
        indexed_terms = indexer.build_index()
        logger.info("Inverted index built with %d unique terms.", indexed_terms)

        logger.info("Phase 3/3: Computing PageRank scores...")
        pagerank_pages = pagerank_engine.compute_and_store()
        logger.info("PageRank scores computed for %d pages.", pagerank_pages)
        index_duration = time.time() - index_start
    else:
        logger.info("Skipping indexing and PageRank as requested (--skip-indexing).")

    total_duration = time.time() - start_time
    summary = {
        "status": "SUCCESS",
        "pages_crawled": new_pages_crawled,
        "total_database_pages": final_page_count,
        "indexed_terms": indexed_terms,
        "pagerank_pages": pagerank_pages,
        "crawl_duration_seconds": round(crawl_duration, 1),
        "index_duration_seconds": round(index_duration, 1),
        "total_duration_seconds": round(total_duration, 1),
    }

    logger.info("==========================================================")
    logger.info("DAILY PIPELINE SUMMARY:")
    for k, v in summary.items():
        logger.info("  %s: %s", k, v)
    logger.info("==========================================================")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run daily crawl, BM25 indexing, and PageRank.")
    parser.add_argument(
        "--pages",
        type=int,
        default=int(os.getenv("DAILY_PAGES", "25000")),
        help="Number of new pages to crawl (default: 25000 or $env:DAILY_PAGES)",
    )
    parser.add_argument(
        "--skip-indexing",
        action="store_true",
        help="Skip rebuilding the inverted index and PageRank.",
    )
    args = parser.parse_args()

    run_daily_pipeline(pages_to_crawl=args.pages, skip_indexing=args.skip_indexing)
