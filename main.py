"""
main.py
=======
Command-line entry point for the SOUL Search Engine.

Usage:
    python main.py          # Starts the search server on port 5000
    python main.py serve    # Starts the search server
"""

from __future__ import annotations

import argparse
import logging
import sys

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def cmd_serve(host: str = config.HOST, port: int = config.PORT) -> None:
    """Starts the SOUL search application."""
    from app import app

    logger.info("Starting SOUL Search Engine on %s:%d ...", host, port)
    app.run(host=host, port=port, debug=False)


def main() -> None:
    """Parses CLI arguments and starts the search engine."""
    parser = argparse.ArgumentParser(description="SOUL Search Engine Server.")
    parser.add_argument(
        "command",
        nargs="?",
        default="serve",
        choices=["serve"],
        help="Command to run (default: serve)",
    )
    parser.add_argument("--host", default=config.HOST, help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=config.PORT, help="Port to listen on (default: 5000)")

    args = parser.parse_args()
    cmd_serve(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
