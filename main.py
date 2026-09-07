"""
main.py
=======
Command-line entry point for the Entertainment Search Engine.

Usage:
    python main.py crawl    # Run the BFS crawler over all 50 seed sites
    python main.py index    # Build the inverted index and compute PageRank
    python main.py serve    # Start the Flask app on 0.0.0.0:5000
"""

from __future__ import annotations

import argparse
import logging
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cmd_crawl() -> None:
    """Runs the BFS web crawler over all configured seed sites."""
    from crawler import run_crawler

    logger.info("Starting crawl...")
    total = run_crawler()
    logger.info("Crawl finished. %d pages stored.", total)


def cmd_index() -> None:
    """Builds the inverted index and computes PageRank scores."""
    from indexer import indexer
    from pagerank import pagerank_engine

    logger.info("Building inverted index...")
    term_count = indexer.build_index()
    logger.info("Inverted index built with %d unique terms.", term_count)

    logger.info("Computing PageRank...")
    page_count = pagerank_engine.compute_and_store()
    logger.info("PageRank computed and stored for %d pages.", page_count)


def cmd_daily(pages: int = 25000) -> None:
    """Runs the automated daily pipeline: crawl, index, and compute PageRank."""
    from daily_crawl import run_daily_pipeline

    run_daily_pipeline(pages_to_crawl=pages)


def cmd_serve() -> None:
    """Starts the Flask development server on 0.0.0.0:5000."""
    from app import app

    logger.info("Starting Flask server on 0.0.0.0:5000 ...")
    app.run(host="0.0.0.0", port=5000, debug=False)


def main() -> None:
    """Parses CLI arguments and dispatches to the appropriate command."""
    parser = argparse.ArgumentParser(
        description="Entertainment Search Engine CLI (crawl / index / daily / serve)."
    )
    parser.add_argument(
        "command",
        choices=["crawl", "index", "daily", "serve"],
        help="Which operation to run.",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=25000,
        help="Number of pages to crawl for the daily pipeline (default: 25000).",
    )
    args = parser.parse_args()

    if args.command == "crawl":
        cmd_crawl()
    elif args.command == "index":
        cmd_index()
    elif args.command == "daily":
        cmd_daily(pages=args.pages)
    elif args.command == "serve":
        cmd_serve()
    else:  # pragma: no cover - argparse enforces valid choices
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
