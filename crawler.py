"""
crawler.py
==========
Breadth-First Search (BFS), multi-threaded, polite web crawler.

Starts from the 50 seed URLs in `config.TARGET_SITES` and expands
outward level-by-level using a thread pool (max 5 workers). Respects
robots.txt, applies a per-domain rate limit, rotates User-Agent strings,
skips non-HTML content, and canonicalizes URLs to avoid duplicate work.
Every successfully fetched page is upserted into the `raw_pages`
MongoDB collection via `database.db`.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
import urllib.robotparser as robotparser
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Deque, Dict, List, Optional, Set
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

import config
from database import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def canonicalize_url(url: str) -> str:
    """Normalizes a URL so equivalent links map to the same string.

    Strips URL fragments, lowercases the scheme/host, removes a trailing
    slash (except for bare domain roots), and drops empty query strings.

    Args:
        url: The raw URL to canonicalize.

    Returns:
        The canonicalized URL string.
    """
    url, _frag = urldefrag(url)
    parsed = urlparse(url)
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    query = parsed.query
    canonical = urlunparse((scheme, netloc, path, "", query, ""))
    return canonical


def is_crawlable_url(url: str) -> bool:
    """Checks whether a URL is a plausible HTML page worth fetching.

    Args:
        url: Canonicalized URL to check.

    Returns:
        False if the URL points to an obviously non-HTML resource.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    path_lower = parsed.path.lower()
    return not path_lower.endswith(config.SKIP_EXTENSIONS)


class RateLimiter:
    """Enforces a minimum delay between requests to the same domain."""

    def __init__(self, min_interval: float = config.RATE_LIMIT_SECONDS) -> None:
        """Initializes the limiter.

        Args:
            min_interval: Minimum seconds allowed between two requests to
                the same domain.
        """
        self._min_interval = min_interval
        self._last_request: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, domain: str) -> None:
        """Blocks the calling thread until it is safe to hit `domain` again."""
        with self._lock:
            now = time.time()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last
            wait_time = self._min_interval - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request[domain] = time.time()


class RobotsCache:
    """Caches parsed robots.txt files per domain to avoid re-fetching."""

    def __init__(self) -> None:
        self._cache: Dict[str, robotparser.RobotFileParser] = {}
        self._lock = threading.Lock()

    def can_fetch(self, url: str, user_agent: str) -> bool:
        """Determines whether `url` may be fetched per its site's robots.txt.

        Args:
            url: The URL under consideration.
            user_agent: The User-Agent string that would be used.

        Returns:
            True if crawling is permitted (or robots.txt is unavailable).
        """
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            rp = self._cache.get(base)
            if rp is None:
                rp = robotparser.RobotFileParser()
                robots_url = urljoin(base, "/robots.txt")
                try:
                    r = requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=5)
                    if r.status_code == 200:
                        rp.parse(r.text.splitlines())
                    else:
                        rp = None  # 404/403 -> permissive
                except Exception:
                    rp = None
                self._cache[base] = rp
        if rp is None:
            return True
        try:
            return rp.can_fetch(user_agent, url) or rp.can_fetch("*", url)
        except Exception:
            return True


class Crawler:
    """BFS multi-threaded crawler over the configured seed sites.

    Attributes:
        max_pages: Hard cap on total pages crawled across the whole run.
        visited: Thread-safe set of canonicalized URLs already processed.
    """

    def __init__(self, max_pages: int = config.MAX_TOTAL_PAGES) -> None:
        """Initializes crawler state.

        Args:
            max_pages: Global hard stop on the number of pages crawled.
        """
        self.max_pages = max_pages
        self.visited: Set[str] = set()
        self._visited_lock = threading.Lock()
        self._domain_counts: Dict[str, int] = defaultdict(int)
        self._domain_lock = threading.Lock()
        self._pages_crawled = 0
        self._counter_lock = threading.Lock()
        self.rate_limiter = RateLimiter()
        self.robots_cache = RobotsCache()
        self.session = requests.Session()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self, seed_urls: Optional[List[str]] = None) -> int:
        """Runs the BFS crawl to completion or until the page cap is hit.

        Args:
            seed_urls: Optional override for the seed URL list; defaults
                to `config.TARGET_SITES`.

        Returns:
            The total number of pages successfully crawled in this run.
        """
        seeds = seed_urls or config.TARGET_SITES
        queue: Deque[str] = deque(canonicalize_url(u) for u in seeds)

        with self._visited_lock:
            for url in list(queue):
                self.visited.add(url)

        with ThreadPoolExecutor(max_workers=config.MAX_WORKERS) as executor:
            while queue and self._pages_crawled < self.max_pages:
                # Pull a batch sized to the worker pool for this BFS level.
                batch: List[str] = []
                while queue and len(batch) < config.MAX_WORKERS:
                    batch.append(queue.popleft())

                futures = {executor.submit(self._process_url, url): url for url in batch}
                for future in futures:
                    try:
                        new_links = future.result()
                    except Exception as exc:
                        logger.error("Worker failed for %s: %s", futures[future], exc)
                        new_links = []

                    for link in new_links:
                        if self._pages_crawled >= self.max_pages:
                            break
                        with self._visited_lock:
                            if link in self.visited:
                                continue
                            self.visited.add(link)
                        queue.append(link)

        logger.info("Crawl complete. Total pages crawled: %d", self._pages_crawled)
        return self._pages_crawled

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _process_url(self, url: str) -> List[str]:
        """Fetches, parses, and stores a single URL; returns discovered links.

        Args:
            url: Canonicalized URL to fetch.

        Returns:
            List of canonicalized outbound links found on the page (only
            returned if the page was successfully crawled and under cap).
        """
        with self._counter_lock:
            if self._pages_crawled >= self.max_pages:
                return []

        if db.url_exists(url):
            return []

        if not is_crawlable_url(url):
            return []

        domain = urlparse(url).netloc.lower()
        with self._domain_lock:
            if config.MAX_PAGES_PER_DOMAIN > 0 and self._domain_counts[domain] >= config.MAX_PAGES_PER_DOMAIN:
                return []

        user_agent = random.choice(config.USER_AGENTS)

        try:
            if not self.robots_cache.can_fetch(url, user_agent):
                logger.info("Skipping (robots.txt disallow): %s", url)
                return []
        except Exception:
            pass

        domain = urlparse(url).netloc
        self.rate_limiter.wait(domain)

        try:
            headers = {"User-Agent": user_agent}
            response = self.session.get(
                url,
                headers=headers,
                timeout=config.REQUEST_TIMEOUT,
                allow_redirects=True,
                stream=True,
            )
        except requests.RequestException as exc:
            logger.warning("Request failed for %s: %s", url, exc)
            return []

        try:
            content_type = response.headers.get("Content-Type", "")
            if not any(ct in content_type for ct in config.ALLOWED_CONTENT_TYPES):
                response.close()
                return []

            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > config.MAX_CONTENT_LENGTH_BYTES:
                response.close()
                return []

            if response.status_code != 200:
                response.close()
                return []

            html = response.text
            response.close()
        except Exception as exc:
            logger.warning("Failed to read response body for %s: %s", url, exc)
            return []

        try:
            page_doc, links = self._parse_page(url, domain, html)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", url, exc)
            return []

        if db.upsert_page(page_doc):
            with self._counter_lock:
                self._pages_crawled += 1
                count = self._pages_crawled
            with self._domain_lock:
                self._domain_counts[domain.lower()] += 1
            logger.info("Crawled [%d] pages | Current: %s", count, url)

        return links

    def _parse_page(self, url: str, domain: str, html: str) -> tuple:
        """Extracts title, meta description, text content, and links.

        Args:
            url: The canonical URL of the page.
            domain: The page's network location (host).
            html: Raw HTML source.

        Returns:
            A tuple of (page_document_dict, list_of_canonical_links).
        """
        soup = BeautifulSoup(html, "html.parser")

        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"})
        if meta_tag and meta_tag.get("content"):
            meta_desc = meta_tag["content"].strip()

        # Remove non-visible / non-content elements before text extraction.
        for tag in soup(["script", "style", "noscript", "head", "template"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)

        # Strip JavaScript template literals (e.g. ${ keyword }, ${expr})
        # that leak through when sites use client-side rendering.
        text = re.sub(r'\$\{[^}]*\}', '', text)
        # Collapse runs of whitespace left by removals.
        text = re.sub(r'[ \t]{2,}', ' ', text).strip()

        links: List[str] = []
        seen_local: Set[str] = set()
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"].strip()
            if not href or href.startswith(("mailto:", "javascript:", "tel:")):
                continue
            absolute = urljoin(url, href)
            canonical = canonicalize_url(absolute)
            if canonical not in seen_local and is_crawlable_url(canonical):
                seen_local.add(canonical)
                links.append(canonical)

        page_doc = {
            "url": url,
            "domain": domain,
            "title": title,
            "meta_description": meta_desc,
            "content": text,
            "links": links,
            "crawled_at": datetime.utcnow(),
        }
        return page_doc, links


def run_crawler() -> int:
    """Convenience entry point used by `main.py crawl`.

    Returns:
        The number of pages crawled during this run.
    """
    crawler = Crawler()
    return crawler.run()


if __name__ == "__main__":
    run_crawler()
