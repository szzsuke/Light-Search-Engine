"""
app.py
======
Flask web application exposing:
  - GET /        A 100% raw, basic HTML search page (zero CSS, zero scripts, basic search box).
  - GET /search  A JSON API returning the search response schema.
  - GET /api/reader  Clean reader view endpoint.
  - GET /api/knowledge Instant answer knowledge graph endpoint.
"""

from __future__ import annotations

import os
from html import escape
from typing import Any, Dict

from flask import Flask, Response, jsonify, render_template, request, send_from_directory

from ddg_knowledge import get_instant_answer
from reader import extract_clean_article
from search_engine import search_engine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "assets")
)
app.config["TEMPLATES_AUTO_RELOAD"] = True


@app.after_request
def add_cors_headers(response: Response) -> Response:
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/favicon.ico")
def favicon() -> Response:
    return Response(status=204)


def render_page(search_result: Dict[str, Any] | None = None) -> str:
    """Builds a 100% raw, basic HTML search interface with zero CSS."""
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

        # Knowledge Panel (Pure basic HTML)
        if kp:
            kp_heading = escape(kp.get("heading", ""))
            kp_abstract = escape(kp.get("abstract", ""))
            kp_img = kp.get("image_url", "")
            kp_source = escape(kp.get("source", "Wikipedia"))
            kp_url = escape(kp.get("source_url", ""))

            img_tag = f'<p><img src="{kp_img}" alt="{kp_heading}"></p>' if kp_img else ""
            source_link = f'<p><a href="{kp_url}" rel="noopener noreferrer">Source: {kp_source}</a></p>' if kp_url else ""

            knowledge_html = f"""
            <aside>
                <h2>{kp_heading}</h2>
                {img_tag}
                <p>{kp_abstract}</p>
                {source_link}
            </aside>
            <hr>
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
                <li>
                    <h3><a href="{url_escaped}" rel="noopener noreferrer">{title_escaped}</a></h3>
                    <small>{domain_escaped} - <a href="{url_escaped}" rel="noopener noreferrer">{url_escaped}</a></small>
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
  <title>{query_value + " - " if query_value else ""}Search</title>
</head>
<body>
  <h1><a href="/">Search</a></h1>
  <form action="/" method="get">
    <input type="text" name="q" value="{query_value}" autofocus required>
    <button type="submit">Search</button>
  </form>
  {corrected_banner}
  {results_html}
</body>
</html>"""
    return html


@app.route("/", methods=["GET"])
def index() -> Response | str:
    """Serves the interactive GPU particle loop frontend."""
    template_path = os.path.join(BASE_DIR, "templates", "index.html")
    if os.path.exists(template_path):
        return render_template("index.html")
    root_index = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(root_index):
        with open(root_index, "r", encoding="utf-8") as f:
            return f.read(), 200, {"Content-Type": "text/html; charset=utf-8"}
    return render_template("index.html")


@app.route("/assets/<path:filename>", methods=["GET"])
def serve_assets(filename: str) -> Response:
    """Serves static assets for the Light Search Engine frontend."""
    return send_from_directory(os.path.join(BASE_DIR, "assets"), filename)


@app.route("/search", methods=["GET"])
@app.route("/api/search", methods=["GET"])
def search_api() -> Response:
    """JSON API endpoint for search.

    Query params:
        q: The search query (required).
        tab / mode: Search tab ('all', 'images', 'news', 'videos').
        limit: Max number of results to return (default 10).
        offset: Offset for infinite scroll pagination (default 0).
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing required query parameter 'q'."}), 400

    mode = request.args.get("tab") or request.args.get("mode") or "all"

    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 50))

    try:
        offset = int(request.args.get("offset", 0))
    except ValueError:
        offset = 0
    safe_param = request.args.get("safe", "1").strip().lower()
    safe = safe_param not in ("0", "false", "off", "no")

    result = search_engine.search(query, offset=offset, limit=limit, mode=mode, safe=safe)
    return jsonify(result)


_POPULAR_DOMAINS = [
    "youtube.com", "reddit.com", "mail.google.com", "gmail.com", "google.com",
    "github.com", "wikipedia.org", "twitter.com", "x.com", "instagram.com",
    "linkedin.com", "facebook.com", "amazon.com", "netflix.com", "chatgpt.com",
    "openai.com", "stackoverflow.com", "spotify.com", "twitch.tv", "medium.com",
    "quora.com", "apple.com", "microsoft.com", "tiktok.com", "huggingface.co",
    "arxiv.org", "discord.com", "pinterest.com", "imdb.com", "dropbox.com"
]


@app.route("/api/suggest", methods=["GET"])
def suggest_api() -> Response:
    """Provides instant predictive domain completions and search queries."""
    import urllib.parse
    import urllib.request
    import json

    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify({"domains": [], "queries": []})

    # Domain prefix matches
    domain_matches = []
    clean_q = q.replace("https://", "").replace("http://", "").replace("www.", "")
    if clean_q.startswith("szz") or "szzsuke".startswith(clean_q):
        domain_matches.append("github.com/szzsuke")

    for d in _POPULAR_DOMAINS:
        if d.startswith(clean_q):
            domain_matches.append(d)
        elif "." in clean_q and clean_q in d:
            domain_matches.append(d)
    domain_matches = domain_matches[:4]

    # Query autocompletions from fast provider
    queries = []
    if any(clean_q.startswith(p) for p in ["szz", "suke", "nish", "maker of light", "creator of light"]) or "szzsuke".startswith(clean_q):
        queries.append("szzsuke")
        queries.append("szzsuke (Maker of Light)")

    try:
        req_url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={urllib.parse.quote(q)}"
        req = urllib.request.Request(req_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if len(data) > 1 and isinstance(data[1], list):
                for item in data[1]:
                    if item.lower() not in [x.lower() for x in queries]:
                        queries.append(item)
                    if len(queries) >= 6:
                        break
    except Exception:
        pass

    return jsonify({"domains": domain_matches, "queries": queries[:6]})


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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
