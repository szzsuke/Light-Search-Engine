"""
gemini_ai.py
============
All Google Gemini AI integrations for the search engine: spell checking,
spam/quality filtering, AI-based relevance scoring, and result
summarization.

Every method is defensive: if the Gemini API key is missing, the API
call fails, times out, or returns an unparseable response, the method
falls back to a safe default instead of raising -- the search engine
must remain fully functional (via TF-IDF + PageRank alone) even with
Gemini completely unavailable.

Uses the new `google-genai` SDK (REST-based, no gRPC required).
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    from google import genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False
    logger.warning("google-genai not installed; Gemini features disabled.")


class GeminiAI:
    """Wrapper around the Gemini API used for all AI-assisted search features."""

    def __init__(self, api_key: str = config.GEMINI_API_KEY, model_name: str = config.GEMINI_MODEL_NAME) -> None:
        """Configures the Gemini client.

        Args:
            api_key: Gemini API key. If empty, all methods silently fall
                back to their safe defaults.
            model_name: Name of the Gemini model to use.
        """
        self._enabled = bool(api_key) and _GENAI_AVAILABLE
        self._client = None
        self._model_name = model_name

        if self._enabled:
            try:
                self._client = genai.Client(api_key=api_key)
                logger.info("Gemini client configured with model: %s", model_name)
            except Exception as exc:
                logger.error("Failed to configure Gemini client: %s", exc)
                self._enabled = False

    def _generate(self, prompt: str) -> str:
        """Sends a prompt to Gemini and returns the raw text response.

        Args:
            prompt: The fully formatted prompt string.

        Returns:
            The response text, or an empty string on any failure.
        """
        if not self._enabled or self._client is None:
            return ""
        try:
            response = self._client.models.generate_content(
                model=self._model_name,
                contents=prompt,
            )
            text = getattr(response, "text", "") or ""
            return text.strip()
        except Exception as exc:
            logger.warning("Gemini API call failed: %s", exc)
            return ""

    # ------------------------------------------------------------------
    # 5.1 Spell check
    # ------------------------------------------------------------------
    def spell_check(self, query: str) -> str:
        """Corrects spelling/grammar in a search query using Gemini."""
        if not query or not query.strip():
            return query

        prompt = (
            "Correct the spelling and grammar of this search query. "
            "Return ONLY the corrected query text, with no quotes, "
            f'explanations, or extra punctuation: "{query}"'
        )
        result = self._generate(prompt)
        if not result:
            return query

        cleaned = result.strip().strip('"').strip("'").strip()
        return cleaned if cleaned else query

    # ------------------------------------------------------------------
    # 5.2 Spam filter
    # ------------------------------------------------------------------
    def is_spam(self, title: str, content: str) -> bool:
        """Rates a page's spam/clickbait likelihood via Gemini."""
        snippet = (content or "")[:2000]
        prompt = (
            f'Analyze this webpage. Title: "{title}"\n'
            f'Content snippet: "{snippet}"\n'
            "Rate how likely this is spam, phishing, clickbait, or useless "
            "filler on a scale of 0 to 10. Return ONLY an integer."
        )
        result = self._generate(prompt)
        if not result:
            return False

        match = re.search(r"-?\d+", result)
        if not match:
            return False

        try:
            score = int(match.group())
        except ValueError:
            return False

        return score >= 7

    # ------------------------------------------------------------------
    # 5.3 AI relevance scoring
    # ------------------------------------------------------------------
    def ai_relevance_score(self, query: str, title: str, content: str) -> float:
        """Scores how relevant a page is to a query using Gemini."""
        snippet = (content or "")[:3000]
        prompt = (
            f'Query: "{query}"\n'
            f'Page Title: "{title}"\n'
            f'Page Content: "{snippet}"\n'
            "Rate the relevance of this page to the query on a scale of "
            "0.0 to 1.0. Return ONLY a float."
        )
        result = self._generate(prompt)
        if not result:
            return 0.5

        match = re.search(r"-?\d+(?:\.\d+)?", result)
        if not match:
            return 0.5

        try:
            score = float(match.group())
        except ValueError:
            return 0.5

        return max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # 5.4 Result summarization
    # ------------------------------------------------------------------
    def summarize_results(self, query: str, results: List[Dict[str, str]]) -> str:
        """Produces a short factual summary answering the user's query."""
        if not results:
            return ""

        formatted_lines = []
        for i, r in enumerate(results, start=1):
            title = r.get("title", "")
            content = (r.get("content", "") or "")[:500]
            formatted_lines.append(f"{i}. {title}: {content}")
        formatted_results = "\n".join(formatted_lines)

        prompt = (
            f'The user searched for: "{query}"\n'
            f"Here are the top results:\n{formatted_results}\n"
            "Provide a concise, factual answer in exactly 1-2 sentences "
            "(2 lines maximum). Do not exceed 2 lines. No bullet points."
        )
        result = self._generate(prompt)
        return result if result else ""


# Module-level singleton for convenient importing elsewhere.
gemini_ai = GeminiAI()
