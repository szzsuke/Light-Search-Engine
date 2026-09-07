"""
app.py
======
Flask web application exposing:
  - GET /        A clean, basic HTML search page (minimal HTML structure, no bloated frontend).
  - GET /search  A JSON API returning the search response schema.
  - GET /api/reader  Clean reader view endpoint.
  - GET /api/knowledge Instant answer knowledge graph endpoint.
"""

from __future__ import annotations

from html import escape
from typing import Any, Dict

from flask import Flask, Response, jsonify, request

from ddg_knowledge import get_instant_answer
from reader import extract_clean_article
from search_engine import search_engine

app = Flask(__name__)


@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


def render_page(search_result: Dict[str, Any] | None = None) -> str:
    """Builds a basic, clean HTML search interface with zero bloated frontend."""
    query_value = ""
    results_html = ""
    knowledge_html = ""
    corrected_banner = ""

    if search_result is not None:
        query_value = escape(search_result.get("original_query", ""))
        corrected = escape(search_result.get("corrected_query", ""))
        total = search_result.get("total_results", 0)
        kp = search_result.get("knowledge_panel")

        if corrected and corrected.lower() != query_value.lower():
            corrected_banner = f'<p>Did you mean: <a href="/?q={corrected}"><strong>{corrected}</strong></a></p>'

        # Knowledge Panel (Basic HTML block)
        if kp:
            kp_heading = escape(kp.get("heading", ""))
            kp_abstract = escape(kp.get("abstract", ""))
            kp_img = kp.get("image_url", "")
            kp_source = escape(kp.get("source", "Wikipedia"))
            kp_url = escape(kp.get("source_url", ""))

            img_tag = f'<p><img src="{kp_img}" alt="{kp_heading}" style="max-width:220px; height:auto;" /></p>' if kp_img else ""
            source_link = f'<p><a href="{kp_url}" target="_blank" rel="noopener noreferrer">Source: {kp_source} &rarr;</a></p>' if kp_url else ""

            knowledge_html = f"""
            <aside style="border: 1px solid #ccc; padding: 12px; margin: 15px 0;">
                <h2>{kp_heading}</h2>
                {img_tag}
                <p>{kp_abstract}</p>
                {source_link}
            </aside>
            """

        # Search Results
        results = search_result.get("results", [])
        if results:
            items_html = f"<p>About {total} results</p><ol>"
            for r in results:
                url_escaped = escape(r["url"])
                domain_escaped = escape(r["domain"])
                title_escaped = escape(r["title"] or r["url"])
                snippet_escaped = escape(r["snippet"])

                items_html += f"""
                <li style="margin-bottom: 16px;">
                    <h3><a href="{url_escaped}" target="_blank" rel="noopener noreferrer">{title_escaped}</a></h3>
                    <small>{domain_escaped} - <a href="{url_escaped}" target="_blank" rel="noopener noreferrer">{url_escaped}</a></small>
                    <p>{snippet_escaped}</p>
                </li>
                """
            items_html += "</ol>"
        else:
            items_html = "<p>No results found. Try another query.</p>"

        results_html = f"{knowledge_html}\n{items_html}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="referrer" content="no-referrer">
  <title>{query_value + " - " if query_value else ""}SOUL Search</title>
</head>
<body style="font-family: sans-serif; max-width: 800px; margin: 20px auto; padding: 0 15px; line-height: 1.5;">
  <h1><a href="/" style="text-decoration: none; color: inherit;">SOUL Search</a></h1>
  <form action="/" method="get">
    <input type="text" name="q" value="{query_value}" placeholder="Search..." style="font-size: 1rem; padding: 6px 10px; width: 70%;" autofocus required />
    <button type="submit" style="font-size: 1rem; padding: 6px 14px; cursor: pointer;">Search</button>
  </form>
  {corrected_banner}
  {results_html}
</body>
</html>"""
    return html


@app.route("/", methods=["GET"])
def index() -> Response:
    """Serves the clean basic HTML search page, running a search if `q` is present."""
    query = request.args.get("q", "").strip()
    result = None
    if query:
        result = search_engine.search(query, top_n=12)
    return Response(render_page(result), mimetype="text/html")


@app.route("/search", methods=["GET"])
@app.route("/api/search", methods=["GET"])
def search_api() -> Response:
    """JSON API endpoint for search.

    Query params:
        q: The search query (required).
        limit: Max number of results to return (default 10).
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


@app.route("/api/reader", methods=["GET"])
def clean_reader_api() -> Response:
    """1-Click Clean Reader endpoint: strips ads, popups, and trackers for any URL."""
    target_url = request.args.get("url", "").strip()
    if not target_url:
        return jsonify({"status": "error", "message": "Missing 'url' query parameter."}), 400

    article = extract_clean_article(target_url)
    return jsonify(article)


@app.route("/api/knowledge", methods=["GET"])
def knowledge_api() -> Response:
    """DuckDuckGo Instant Answer / Knowledge Graph proxy endpoint."""
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"status": "error", "message": "Missing 'q' query parameter."}), 400

    data = get_instant_answer(query)
    if not data:
        return jsonify({"status": "not_found", "message": "No entity match found."}), 404

    return jsonify({"status": "success", "data": data})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
