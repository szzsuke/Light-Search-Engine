"""
database.py
============
MongoDB access layer for the Entertainment Search Engine.

Provides a single `Database` class that owns a pooled `MongoClient`,
exposes the four collections used by the system (`raw_pages`,
`inverted_index`, `page_rank`, `search_logs`), and creates all required
indexes idempotently. Every public method wraps PyMongo calls in
try/except so that a transient MongoDB disconnection never crashes the
calling module.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.errors import PyMongoError

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Database:
    """Thin wrapper around a pooled MongoDB connection.

    Attributes:
        client: The underlying pooled `MongoClient` instance.
        db: The application database handle.
        raw_pages: Collection storing crawled page documents.
        inverted_index: Collection storing the term -> postings index.
        page_rank: Collection storing per-URL PageRank scores.
        search_logs: Collection storing a history of user queries.
    """

    def __init__(self, uri: str = config.MONGO_URI, db_name: str = config.MONGO_DB_NAME) -> None:
        """Initializes the MongoDB connection pool and ensures indexes exist.

        Args:
            uri: MongoDB connection URI.
            db_name: Name of the database to use.
        """
        self.client: MongoClient = MongoClient(
            uri,
            maxPoolSize=50,
            minPoolSize=1,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
            retryWrites=True,
        )
        self.db = self.client[db_name]

        self.raw_pages: Collection = self.db[config.COLLECTION_RAW_PAGES]
        self.inverted_index: Collection = self.db[config.COLLECTION_INVERTED_INDEX]
        self.page_rank: Collection = self.db[config.COLLECTION_PAGE_RANK]
        self.search_logs: Collection = self.db[config.COLLECTION_SEARCH_LOGS]
        self.index_meta: Collection = self.db["index_metadata"]

        self._ensure_indexes()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    def _ensure_indexes(self) -> None:
        """Creates all required indexes if they do not already exist."""
        try:
            self.raw_pages.create_index([("url", ASCENDING)], unique=True, name="uniq_url")
            self.raw_pages.create_index([("domain", ASCENDING)], name="idx_domain")

            self.inverted_index.create_index([("term", ASCENDING)], unique=True, name="uniq_term")

            self.page_rank.create_index([("url", ASCENDING)], unique=True, name="uniq_pr_url")

            self.search_logs.create_index([("timestamp", ASCENDING)], name="idx_ts")

            logger.info("MongoDB indexes verified/created successfully.")
        except PyMongoError as exc:
            logger.error("Failed to create indexes: %s", exc)

    def ping(self) -> bool:
        """Checks whether the MongoDB server is reachable.

        Returns:
            True if the server responded to a ping, False otherwise.
        """
        try:
            self.client.admin.command("ping")
            return True
        except PyMongoError as exc:
            logger.error("MongoDB ping failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # raw_pages helpers
    # ------------------------------------------------------------------
    def upsert_page(self, page: Dict[str, Any]) -> bool:
        """Inserts or updates a crawled page document.

        Args:
            page: Dict matching the raw_pages schema (url, domain, title,
                meta_description, content, links, crawled_at).

        Returns:
            True on success, False on failure.
        """
        try:
            self.raw_pages.update_one(
                {"url": page["url"]},
                {"$set": page},
                upsert=True,
            )
            return True
        except PyMongoError as exc:
            logger.error("Failed to upsert page %s: %s", page.get("url"), exc)
            return False

    def url_exists(self, url: str) -> bool:
        """Checks whether a URL has already been crawled.

        Args:
            url: Canonicalized URL to check.

        Returns:
            True if the URL is already stored in raw_pages.
        """
        try:
            return self.raw_pages.count_documents({"url": url}, limit=1) > 0
        except PyMongoError as exc:
            logger.error("url_exists check failed for %s: %s", url, exc)
            return False

    def count_pages(self) -> int:
        """Returns the total number of crawled pages stored."""
        try:
            return self.raw_pages.count_documents({})
        except PyMongoError as exc:
            logger.error("count_pages failed: %s", exc)
            return 0

    def get_page(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetches a single page document by URL."""
        try:
            return self.raw_pages.find_one({"url": url})
        except PyMongoError as exc:
            logger.error("get_page failed for %s: %s", url, exc)
            return None

    def all_pages(self, projection: Optional[Dict[str, int]] = None) -> Iterable[Dict[str, Any]]:
        """Returns a cursor over all crawled pages.

        Args:
            projection: Optional MongoDB projection dict.

        Returns:
            A PyMongo cursor (empty iterator on failure).
        """
        try:
            return self.raw_pages.find({}, projection or {})
        except PyMongoError as exc:
            logger.error("all_pages failed: %s", exc)
            return iter([])

    # ------------------------------------------------------------------
    # inverted_index helpers
    # ------------------------------------------------------------------
    def upsert_term_postings(self, term: str, postings: List[Dict[str, Any]]) -> bool:
        """Replaces the postings list for a given term.

        Args:
            term: The indexed token.
            postings: List of {url, tf, positions} dicts.

        Returns:
            True on success, False on failure.
        """
        try:
            self.inverted_index.update_one(
                {"term": term},
                {"$set": {"term": term, "postings": postings}},
                upsert=True,
            )
            return True
        except PyMongoError as exc:
            logger.error("Failed to upsert postings for term %s: %s", term, exc)
            return False

    def get_postings(self, term: str) -> Optional[Dict[str, Any]]:
        """Fetches the postings document for a single term."""
        try:
            return self.inverted_index.find_one({"term": term})
        except PyMongoError as exc:
            logger.error("get_postings failed for %s: %s", term, exc)
            return None

    def clear_index(self) -> None:
        """Deletes all inverted index documents (used before a rebuild)."""
        try:
            self.inverted_index.delete_many({})
        except PyMongoError as exc:
            logger.error("clear_index failed: %s", exc)

    def set_index_meta(self, meta: Dict[str, Any]) -> bool:
        """Persists collection statistics (avg document length, total docs)."""
        try:
            self.index_meta.update_one({"_id": "stats"}, {"$set": meta}, upsert=True)
            return True
        except PyMongoError as exc:
            logger.error("set_index_meta failed: %s", exc)
            return False

    def get_index_meta(self) -> Dict[str, Any]:
        """Retrieves collection statistics (avg document length, total docs)."""
        try:
            doc = self.index_meta.find_one({"_id": "stats"})
            return doc or {}
        except PyMongoError as exc:
            logger.error("get_index_meta failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # page_rank helpers
    # ------------------------------------------------------------------
    def upsert_page_rank(self, url: str, score: float, domain: str) -> bool:
        """Inserts or updates the PageRank score for a URL."""
        try:
            self.page_rank.update_one(
                {"url": url},
                {"$set": {"url": url, "score": score, "domain": domain}},
                upsert=True,
            )
            return True
        except PyMongoError as exc:
            logger.error("Failed to upsert page_rank for %s: %s", url, exc)
            return False

    def get_page_rank(self, url: str) -> float:
        """Returns the PageRank score for a URL, or 0.0 if missing."""
        try:
            doc = self.page_rank.find_one({"url": url})
            return float(doc["score"]) if doc else 0.0
        except PyMongoError as exc:
            logger.error("get_page_rank failed for %s: %s", url, exc)
            return 0.0

    def clear_page_rank(self) -> None:
        """Deletes all page_rank documents (used before a recompute)."""
        try:
            self.page_rank.delete_many({})
        except PyMongoError as exc:
            logger.error("clear_page_rank failed: %s", exc)

    # ------------------------------------------------------------------
    # search_logs helpers
    # ------------------------------------------------------------------
    def log_search(self, query: str, corrected_query: str, result_count: int) -> None:
        """Records a search query for analytics purposes.

        Args:
            query: The raw user-submitted query.
            corrected_query: The spell-checked query actually used.
            result_count: Number of results returned.
        """
        try:
            self.search_logs.insert_one({
                "query": query,
                "corrected_query": corrected_query,
                "result_count": result_count,
                "timestamp": datetime.utcnow(),
            })
        except PyMongoError as exc:
            logger.error("log_search failed: %s", exc)

    def close(self) -> None:
        """Closes the underlying MongoDB connection pool."""
        try:
            self.client.close()
        except PyMongoError:
            pass


# Module-level singleton so every module can `from database import db`.
db = Database()
