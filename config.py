"""
config.py
=========
Central configuration for the SOUL Search Engine.
Holds tunable values for search retrieval, Gemini AI spell-check, and server settings.
"""

import os

# ---------------------------------------------------------------------------
# Server configuration
# ---------------------------------------------------------------------------
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "5000"))

# ---------------------------------------------------------------------------
# Gemini AI configuration (Spell check & query enhancement)
# ---------------------------------------------------------------------------
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL_NAME: str = os.getenv("GEMINI_MODEL_NAME", "gemini-3.6-flash")

# ---------------------------------------------------------------------------
# Search engine defaults
# ---------------------------------------------------------------------------
DEFAULT_TOP_N: int = 12
REQUEST_TIMEOUT: int = 8  # seconds

# Rotating User-Agent pool for clean web and reader requests
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]
