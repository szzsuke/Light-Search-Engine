"""
app.py
======
Flask web application exposing:

  - GET /        A raw, unstyled HTML search page (no CSS, no JS) that
                  performs a search when a `q` query parameter is present.
  - GET /search   A JSON API returning the exact search response schema.

The HTML page uses only basic tags (form, input, button, h1, h2, p, ol,
li, a, small) with no <style>, <script>, or inline style attributes, as
required for the plain testing interface.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict

from flask import Flask, Response, jsonify, request

from search_engine import search_engine

app = Flask(__name__)


@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def render_page(search_result: Dict[str, Any] | None = None) -> str:
    """Builds the raw HTML page, optionally including search results.

    Args:
        search_result: The dict returned by `SearchEngine.search`, or
            None if no search has been performed yet.

    Returns:
        A complete HTML document as a string, using only basic tags.
    """
    query_value = ""
    results_html = ""

    if search_result is not None:
        query_value = escape(search_result.get("original_query", ""))
        corrected = escape(search_result.get("corrected_query", ""))
        summary = escape(search_result.get("ai_summary", ""))
        total = search_result.get("total_results", 0)

        items_html = ""
        for r in search_result.get("results", []):
            items_html += (
                "<li>"
                f'<a href="{escape(r["url"])}">{escape(r["title"] or r["url"])}</a>'
                f'<p>{escape(r["snippet"])}</p>'
                f'<small>Score: {r["score"]} | Domain: {escape(r["domain"])}</small>'
                "</li>"
            )

        if not items_html:
            items_html = "<li>No results found.</li>"

        results_html = f"""
  <h2>Results ({total})</h2>
  <p><strong>Corrected Query:</strong> {corrected}</p>
  <p><strong>AI Summary:</strong> {summary}</p>
  <ol>
    {items_html}
  </ol>
"""

    html = f"""<!DOCTYPE html>
<html>
<head><title>Entertainment Search Engine</title></head>
<body>
  <h1>Search</h1>
  <form action="/" method="get">
    <input type="text" name="q" value="{query_value}" placeholder="Search..." required>
    <button type="submit">Search</button>
  </form>
  {results_html}
</body>
</html>"""
    return html


@app.route("/", methods=["GET"])
def index() -> Response:
    """Serves the basic HTML search page, running a search if `q` is present.

    Returns:
        A Flask Response containing raw HTML with no CSS or JavaScript.
    """
    query = request.args.get("q", "").strip()
    result = None
    if query:
        result = search_engine.search(query, top_n=10)
    return Response(render_page(result), mimetype="text/html")


@app.route("/search", methods=["GET"])
def search_api() -> Response:
    """JSON API endpoint for programmatic search access.

    Query params:
        q: The search query (required).
        limit: Max number of results to return (default 10).

    Returns:
        JSON matching the SearchEngine.search response schema. Returns
        HTTP 400 if `q` is missing.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing required query parameter 'q'."}), 400

    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 100))

    result = search_engine.search(query, top_n=limit)
    return jsonify(result)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
