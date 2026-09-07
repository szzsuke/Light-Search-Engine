"""
config.py
=========
Central configuration for the Entertainment Search Engine.

Holds all constants used across the crawler, database layer, indexer,
PageRank engine, Gemini AI wrapper, and Flask application. Keeping every
tunable value in one module makes it easy to adjust crawl scope, database
connections, and scoring weights without touching business logic.
"""

import os

# ---------------------------------------------------------------------------
# MongoDB configuration
# ---------------------------------------------------------------------------
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "entertainment_search")

# Collection names
COLLECTION_RAW_PAGES: str = "raw_pages"
COLLECTION_INVERTED_INDEX: str = "inverted_index"
COLLECTION_PAGE_RANK: str = "page_rank"
COLLECTION_SEARCH_LOGS: str = "search_logs"

# ---------------------------------------------------------------------------
# Gemini AI configuration
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-3.6-flash")

# ---------------------------------------------------------------------------
# Crawler configuration
# ---------------------------------------------------------------------------
MAX_TOTAL_PAGES: int = int(os.getenv("MAX_TOTAL_PAGES", "120000"))
MAX_WORKERS: int = 12
MAX_PAGES_PER_DOMAIN: int = int(os.getenv("MAX_PAGES_PER_DOMAIN", "150")) # Enforces genre/domain diversity per run
RATE_LIMIT_SECONDS: float = 1.0  # seconds between requests to the same domain
REQUEST_TIMEOUT: int = 10  # seconds
MAX_CONTENT_LENGTH_BYTES: int = 5_000_000  # skip pages larger than ~5MB

# Only these content types are considered crawlable HTML pages.
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

# File extensions to skip outright (non-HTML resources).
SKIP_EXTENSIONS = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".rar", ".tar", ".gz", ".mp3", ".mp4", ".avi", ".mov",
    ".wav", ".flac", ".exe", ".dmg", ".css", ".js", ".json", ".xml",
    ".woff", ".woff2", ".ttf", ".eot", ".doc", ".docx", ".xls", ".xlsx",
    ".ppt", ".pptx",
)

# Rotating User-Agent pool to be a good citizen while avoiding trivial
# fingerprinting/blocking by a single static UA string.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 "
    "Firefox/121.0",
]

# ---------------------------------------------------------------------------
# Indexing / search configuration
# ---------------------------------------------------------------------------
DEFAULT_MIN_RESULTS: int = 5
DEFAULT_TOP_N: int = 10

# Minimal English stopword list (kept local to avoid an external NLTK
# download dependency at runtime).
STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an",
    "and", "any", "are", "aren't", "as", "at", "be", "because", "been",
    "before", "being", "below", "between", "both", "but", "by", "can't",
    "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't",
    "doing", "don't", "down", "during", "each", "few", "for", "from",
    "further", "had", "hadn't", "has", "hasn't", "have", "haven't",
    "having", "he", "he'd", "he'll", "he's", "her", "here", "here's",
    "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't",
    "it", "it's", "its", "itself", "let's", "me", "more", "most",
    "mustn't", "my", "myself", "no", "nor", "not", "of", "off", "on",
    "once", "only", "or", "other", "ought", "our", "ours", "ourselves",
    "out", "over", "own", "same", "shan't", "she", "she'd", "she'll",
    "she's", "should", "shouldn't", "so", "some", "such", "than", "that",
    "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're",
    "they've", "this", "those", "through", "to", "too", "under", "until",
    "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're",
    "we've", "were", "weren't", "what", "what's", "when", "when's",
    "where", "where's", "which", "while", "who", "who's", "whom", "why",
    "why's", "with", "won't", "would", "wouldn't", "you", "you'd",
    "you'll", "you're", "you've", "your", "yours", "yourself",
    "yourselves",
}

# ---------------------------------------------------------------------------
# PageRank configuration
# ---------------------------------------------------------------------------
PAGERANK_DAMPING: float = 0.85
PAGERANK_CONVERGENCE_THRESHOLD: float = 0.0001
PAGERANK_MAX_ITERATIONS: int = 200

# ---------------------------------------------------------------------------
# Okapi BM25 & Ranking Parameters (DuckDuckGo / Modern IR Engine)
# ---------------------------------------------------------------------------
BM25_K1: float = 1.5            # Term frequency saturation parameter
BM25_B: float = 0.75            # Document length normalization
BM25_TITLE_WEIGHT: float = 4.0  # Multiplier for query terms appearing in <title>
BM25_URL_WEIGHT: float = 3.0    # Multiplier for query terms appearing in domain/URL

# Composite ranking weights
WEIGHT_BM25: float = 0.55       # Field-weighted BM25 relevance score
WEIGHT_PAGERANK: float = 0.30   # Log-normalized PageRank authority
WEIGHT_PROXIMITY: float = 0.15  # Exact phrase & term proximity bonus
WEIGHT_TFIDF: float = 0.40      # Backward compatibility
WEIGHT_AI_RELEVANCE: float = 0.05

# ---------------------------------------------------------------------------
# Multi-Genre Universal Target Seed URLs
# Covers: News, Tech, Science, Medicine, Finance, Food, Travel, Education,
# Sports, Books, Automotive, Gaming, Culture, and Philosophy.
# ---------------------------------------------------------------------------
TARGET_SITES = [
    # --- World News & Journalism ---
    "https://www.reuters.com",
    "https://apnews.com",
    "https://www.bbc.com/news",
    "https://www.theguardian.com/international",
    "https://www.npr.org",
    "https://www.aljazeera.com",
    "https://news.ycombinator.com",

    # --- Technology, AI & Coding ---
    "https://arstechnica.com",
    "https://techcrunch.com",
    "https://www.theverge.com",
    "https://www.wired.com",
    "https://www.engadget.com",
    "https://github.com",
    "https://stackoverflow.com",
    "https://developer.mozilla.org",
    "https://www.python.org",
    "https://dev.to",

    # --- Science, Space & Medicine ---
    "https://www.nature.com",
    "https://www.scientificamerican.com",
    "https://www.sciencedaily.com",
    "https://phys.org",
    "https://www.nasa.gov",
    "https://www.space.com",
    "https://arxiv.org",
    "https://www.mayoclinic.org",
    "https://www.webmd.com",
    "https://www.healthline.com",

    # --- Business, Finance & Economics ---
    "https://www.investopedia.com",
    "https://www.bloomberg.com",
    "https://www.cnbc.com",
    "https://www.forbes.com",
    "https://finance.yahoo.com",
    "https://www.economist.com",

    # --- Education, History & Philosophy ---
    "https://en.wikipedia.org/wiki/Portal:Contents",
    "https://en.wikipedia.org/wiki/Portal:Science",
    "https://en.wikipedia.org/wiki/Portal:History",
    "https://simple.wikipedia.org",
    "https://www.britannica.com",
    "https://www.khanacademy.org",
    "https://ocw.mit.edu",
    "https://www.coursera.org",
    "https://plato.stanford.edu",
    "https://www.worldhistory.org",
    "https://www.nationalgeographic.com",

    # --- Food, Cooking & Recipes ---
    "https://www.allrecipes.com",
    "https://www.seriouseats.com",
    "https://www.foodnetwork.com",
    "https://www.simplyrecipes.com",
    "https://www.bonappetit.com",
    "https://www.epicurious.com",

    # --- Travel, Geography & Adventure ---
    "https://www.lonelyplanet.com",
    "https://www.tripadvisor.com",
    "https://www.atlasobscura.com",
    "https://www.travelandleisure.com",

    # --- Books, Literature & Arts ---
    "https://www.goodreads.com",
    "https://www.gutenberg.org",
    "https://lithub.com",
    "https://www.poetryfoundation.org",
    "https://www.artsy.net",

    # --- Sports, Fitness & Athletics ---
    "https://www.espn.com",
    "https://www.bbc.com/sport",
    "https://bleacherreport.com",
    "https://theathletic.com",
    "https://www.bodybuilding.com",

    # --- Cars & Automotive ---
    "https://www.caranddriver.com",
    "https://www.motortrend.com",
    "https://www.autoblog.com",
    "https://www.topgear.com",
    "https://jalopnik.com",
    "https://www.motor1.com",
    "https://www.autocar.co.uk",
    "https://en.wikipedia.org/wiki/Portal:Cars",

    # --- Gaming & Entertainment ---
    "https://www.ign.com",
    "https://www.gamespot.com",
    "https://www.polygon.com",
    "https://kotaku.com",
    "https://www.pcgamer.com",
    "https://www.rottentomatoes.com",
    "https://letterboxd.com",
    "https://www.themoviedb.org",
    "https://www.metacritic.com",
    "https://pitchfork.com",
    "https://www.billboard.com",
    "https://variety.com",
    "https://myanimelist.net",
    "https://www.animenewsnetwork.com",
    "https://tvtropes.org",
]
