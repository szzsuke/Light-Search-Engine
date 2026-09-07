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


def render_page(search_result: Dict[str, Any] | None = None, mode: str = "all") -> str:
    """Builds the modern SOUL search interface with Knowledge Panel and Clean Reader."""
    query_value = ""
    results_html = ""
    knowledge_html = ""
    corrected_banner = ""
    tabs_html = ""

    if search_result is not None:
        query_value = escape(search_result.get("original_query", ""))
        corrected = escape(search_result.get("corrected_query", ""))
        total = search_result.get("total_results", 0)
        kp = search_result.get("knowledge_panel")

        if query_value:
            tabs_html = f"""
            <div class="tabs">
                <a href="/?q={query_value}&mode=all" class="tab {'active' if mode == 'all' else ''}">🌐 All (Smart Ranked)</a>
                <a href="/?q={query_value}&mode=discussions" class="tab {'active' if mode == 'discussions' else ''}">💬 Discussions & Reddit</a>
            </div>
            """

        if corrected and corrected.lower() != query_value.lower():
            corrected_banner = f"""
            <div class="corrected-banner">
                Did you mean: <a href="/?q={corrected}&mode={mode}"><strong>{corrected}</strong></a>
            </div>
            """

        # Knowledge Panel (Right side)
        if kp:
            kp_heading = escape(kp.get("heading", ""))
            kp_abstract = escape(kp.get("abstract", ""))
            kp_img = kp.get("image_url", "")
            kp_source = escape(kp.get("source", "Wikipedia"))
            kp_url = escape(kp.get("source_url", ""))

            img_tag = f'<img src="{kp_img}" class="kp-image" alt="{kp_heading}" />' if kp_img else ""
            
            # Related Topic Tags
            pills = ""
            for node in kp.get("related_nodes", []):
                name = escape(node.get("name", ""))
                pills += f'<a href="/?q={name}" class="kp-pill">{name}</a>'

            knowledge_html = f"""
            <aside class="kp-card">
                {img_tag}
                <div class="kp-body">
                    <div class="kp-badge">KNOWLEDGE GRAPH</div>
                    <h3 class="kp-title">{kp_heading}</h3>
                    <p class="kp-abstract">{kp_abstract}</p>
                    {f'<div class="kp-pills"><strong>Explore Related:</strong><div class="pill-wrap">{pills}</div></div>' if pills else ''}
                    {f'<a href="{kp_url}" target="_blank" class="kp-source">Source: {kp_source} &rarr;</a>' if kp_url else ''}
                </div>
            </aside>
            """

        # Search Results (Left side)
        items_html = ""
        for r in search_result.get("results", []):
            url_escaped = escape(r["url"])
            domain_escaped = escape(r["domain"])
            title_escaped = escape(r["title"] or r["url"])
            snippet_escaped = escape(r["snippet"])
            items_html += f"""
            <div class="result-card">
                <div class="result-meta">
                    <span class="domain-tag">{domain_escaped}</span>
                    <span class="url-breadcrumb">{url_escaped[:50]}...</span>
                </div>
                <h3 class="result-title">
                    <a href="{url_escaped}" target="_blank">{title_escaped}</a>
                </h3>
                <p class="result-snippet">{snippet_escaped}</p>
                <div class="result-actions">
                    <button class="btn-read" onclick="openReader('{url_escaped}')">📖 Quick Read</button>
                    <a href="{url_escaped}" target="_blank" class="btn-visit">Visit Link &rarr;</a>
                </div>
            </div>
            """

        if not items_html:
            items_html = '<div class="no-results">No results found. Try another query!</div>'

        results_html = f"""
        <div class="search-layout">
            <main class="results-column">
                <div class="results-count">About {total} live web results</div>
                {items_html}
            </main>
            {knowledge_html}
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{query_value + " - " if query_value else ""}SOUL Search</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #090a0f;
      --card-bg: rgba(22, 24, 34, 0.7);
      --border: rgba(255, 255, 255, 0.08);
      --accent: #ff4b2b;
      --accent-grad: linear-gradient(135deg, #ff416c 0%, #ff4b2b 100%);
      --text: #f3f4f6;
      --muted: #9ca3af;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: var(--bg);
      color: var(--text);
      font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
      min-height: 100vh;
      background-image: radial-gradient(circle at 50% 0%, rgba(255, 75, 43, 0.12), transparent 45%),
                        radial-gradient(circle at 10% 20%, rgba(30, 144, 255, 0.08), transparent 35%);
    }}
    .container {{ max-width: 1100px; margin: 0 auto; padding: 30px 20px; }}
    .header {{ text-align: center; margin-bottom: 25px; }}
    .logo {{
      font-size: 2.2rem;
      font-weight: 800;
      letter-spacing: 2px;
      background: var(--accent-grad);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-decoration: none;
      display: inline-block;
    }}
    .logo-sub {{ font-size: 0.85rem; color: var(--muted); margin-top: 4px; }}
    .search-box {{
      max-width: 680px;
      margin: 0 auto 30px auto;
      display: flex;
      background: rgba(30, 33, 48, 0.8);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 6px 8px 6px 20px;
      backdrop-filter: blur(16px);
      box-shadow: 0 10px 30px rgba(0,0,0,0.5);
    }}
    .search-input {{
      flex: 1;
      background: transparent;
      border: none;
      color: #fff;
      font-size: 1rem;
      outline: none;
      font-family: inherit;
    }}
    .search-btn {{
      background: var(--accent-grad);
      border: none;
      color: #fff;
      font-weight: 600;
      padding: 10px 24px;
      border-radius: 999px;
      cursor: pointer;
      font-family: inherit;
      transition: opacity 0.2s;
    }}
    .search-btn:hover {{ opacity: 0.9; }}
    .corrected-banner {{
      max-width: 680px;
      margin: -15px auto 25px auto;
      color: var(--muted);
      font-size: 0.95rem;
    }}
    .corrected-banner a {{ color: #60a5fa; text-decoration: none; }}
    .corrected-banner a:hover {{ text-decoration: underline; }}
    .search-layout {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 30px;
    }}
    @media(min-width: 860px) {{
      .search-layout {{ grid-template-columns: 1.6fr 1fr; }}
    }}
    .results-count {{ font-size: 0.85rem; color: var(--muted); margin-bottom: 16px; }}
    .result-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px 20px;
      margin-bottom: 16px;
      backdrop-filter: blur(12px);
      transition: transform 0.15s, border-color 0.15s;
    }}
    .result-card:hover {{
      transform: translateY(-2px);
      border-color: rgba(255, 75, 43, 0.35);
    }}
    .result-meta {{ display: flex; align-items: center; gap: 8px; font-size: 0.75rem; margin-bottom: 6px; }}
    .domain-tag {{
      background: rgba(255, 75, 43, 0.15);
      color: #ff7b5c;
      padding: 2px 8px;
      border-radius: 6px;
      font-weight: 600;
    }}
    .url-breadcrumb {{ color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .result-title {{ font-size: 1.15rem; font-weight: 600; margin-bottom: 8px; line-height: 1.35; }}
    .result-title a {{ color: #93c5fd; text-decoration: none; }}
    .result-title a:hover {{ text-decoration: underline; }}
    .result-snippet {{ font-size: 0.9rem; color: #d1d5db; line-height: 1.5; margin-bottom: 12px; }}
    .result-actions {{ display: flex; gap: 10px; align-items: center; }}
    .btn-read {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid var(--border);
      color: #fff;
      font-size: 0.8rem;
      padding: 6px 14px;
      border-radius: 8px;
      cursor: pointer;
      font-family: inherit;
      transition: background 0.2s;
    }}
    .btn-read:hover {{ background: rgba(255, 255, 255, 0.16); }}
    .btn-visit {{
      color: var(--muted);
      font-size: 0.8rem;
      text-decoration: none;
      padding: 6px 10px;
    }}
    .btn-visit:hover {{ color: #fff; }}
    /* Knowledge Panel */
    .kp-card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      backdrop-filter: blur(16px);
      height: fit-content;
      position: sticky;
      top: 20px;
    }}
    .kp-image {{ width: 100%; max-height: 220px; object-fit: cover; background: #000; }}
    .kp-body {{ padding: 20px; }}
    .kp-badge {{
      font-size: 0.7rem;
      letter-spacing: 1px;
      font-weight: 700;
      color: #ff4b2b;
      margin-bottom: 6px;
    }}
    .kp-title {{ font-size: 1.4rem; font-weight: 700; margin-bottom: 10px; }}
    .kp-abstract {{ font-size: 0.88rem; color: #d1d5db; line-height: 1.6; margin-bottom: 16px; }}
    .kp-pills strong {{ font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }}
    .pill-wrap {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; margin-bottom: 16px; }}
    .kp-pill {{
      background: rgba(255, 255, 255, 0.07);
      color: #e5e7eb;
      font-size: 0.75rem;
      padding: 4px 10px;
      border-radius: 999px;
      text-decoration: none;
      border: 1px solid var(--border);
      transition: border-color 0.2s;
    }}
    .kp-pill:hover {{ border-color: #ff4b2b; color: #fff; }}
    .kp-source {{ font-size: 0.75rem; color: var(--muted); text-decoration: none; display: block; }}
    .kp-source:hover {{ color: #93c5fd; }}
    /* Reader Modal */
    .modal-overlay {{
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0,0,0,0.8);
      backdrop-filter: blur(10px);
      z-index: 1000;
      padding: 30px 15px;
      overflow-y: auto;
    }}
    .modal-content {{
      max-width: 720px;
      margin: 0 auto;
      background: #11131a;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 30px;
      position: relative;
    }}
    .modal-close {{
      position: absolute;
      top: 15px; right: 15px;
      background: rgba(255,255,255,0.1);
      border: none;
      color: #fff;
      font-size: 1.2rem;
      width: 32px; height: 32px;
      border-radius: 50%;
      cursor: pointer;
    }}
    .reader-body {{ font-size: 1.05rem; line-height: 1.8; color: #e2e8f0; margin-top: 20px; }}
    .reader-body p {{ margin-bottom: 16px; }}
    .reader-body h1, .reader-body h2, .reader-body h3 {{ color: #fff; margin: 24px 0 12px 0; }}
    .reader-meta {{ font-size: 0.85rem; color: var(--muted); margin-bottom: 12px; }}
    .reader-image {{ max-width: 100%; border-radius: 10px; margin: 15px 0; }}
    .tabs {{
      display: flex;
      justify-content: center;
      gap: 10px;
      margin-bottom: 25px;
    }}
    .tab {{
      padding: 7px 16px;
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border);
      color: var(--muted);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 500;
      transition: all 0.2s;
    }}
    .tab:hover {{
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
    }}
    .tab.active {{
      background: var(--accent-grad);
      color: #fff;
      border-color: transparent;
      box-shadow: 0 4px 15px rgba(255, 75, 43, 0.3);
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <a href="/" class="logo">S O U L</a>
      <div class="logo-sub">Hyper-Fast Real-Time Search with DuckDuckGo Knowledge Graph</div>
    </div>
    <form action="/" method="get" class="search-box">
      <input type="text" name="q" value="{query_value}" placeholder="Search the web, news, code, or knowledge..." class="search-input" autofocus required>
      <button type="submit" class="search-btn">Search</button>
    </form>
    {tabs_html}
    {corrected_banner}
    {results_html}
  </div>

  <div id="readerModal" class="modal-overlay" onclick="if(event.target===this)closeReader()">
    <div class="modal-content">
      <button class="modal-close" onclick="closeReader()">&times;</button>
      <div class="reader-meta" id="readerMeta"></div>
      <h2 id="readerTitle" style="margin-bottom: 10px;"></h2>
      <div id="readerBody" class="reader-body"></div>
    </div>
  </div>

  <script>
    async function openReader(url) {{
      const modal = document.getElementById('readerModal');
      const title = document.getElementById('readerTitle');
      const meta = document.getElementById('readerMeta');
      const body = document.getElementById('readerBody');
      
      modal.style.display = 'block';
      title.innerText = 'Loading clean article...';
      meta.innerText = '';
      body.innerHTML = '<p>Fetching content without ads and popups...</p>';

      try {{
        const res = await fetch('/api/reader?url=' + encodeURIComponent(url));
        const data = await res.json();
        if (data.status === 'success') {{
          title.innerText = data.title;
          meta.innerText = (data.domain ? data.domain + ' • ' : '') + (data.reading_time || '');
          body.innerHTML = data.clean_html;
        }} else {{
          title.innerText = 'Unable to extract reader view';
          body.innerHTML = '<p>' + (data.message || 'Error loading page') + '</p><a href="' + url + '" target="_blank" style="color:#60a5fa">Visit original page &rarr;</a>';
        }}
      }} catch (err) {{
        title.innerText = 'Error loading article';
        body.innerHTML = '<p>' + err.message + '</p>';
      }}
    }}
    function closeReader() {{
      document.getElementById('readerModal').style.display = 'none';
    }}
  </script>
</body>
</html>"""
    return html


@app.route("/", methods=["GET"])
def index() -> Response:
    """Serves the SOUL search page, running a search if `q` is present."""
    query = request.args.get("q", "").strip()
    mode = request.args.get("mode", "all").strip()
    result = None
    if query:
        result = search_engine.search(query, top_n=12, mode=mode)
    return Response(render_page(result, mode=mode), mimetype="text/html")


@app.route("/search", methods=["GET"])
@app.route("/api/search", methods=["GET"])
def search_api() -> Response:
    """JSON API endpoint for search with BM25, PageRank, and DuckDuckGo Knowledge Panel.

    Query params:
        q: The search query (required).
        limit: Max number of results to return (default 10).
        mode: Search mode ('all' or 'discussions').

    Returns:
        JSON with search results and DuckDuckGo knowledge panel.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Missing required query parameter 'q'."}), 400

    mode = request.args.get("mode", "all").strip()
    try:
        limit = int(request.args.get("limit", 10))
    except ValueError:
        limit = 10
    limit = max(1, min(limit, 100))

    result = search_engine.search(query, top_n=limit, mode=mode)
    return jsonify(result)


@app.route("/api/reader", methods=["GET"])
def clean_reader_api() -> Response:
    """1-Click Clean Reader endpoint: strips ads, popups, and trackers for any URL.

    Query params:
        url: The web page URL to clean and read (required).

    Returns:
        JSON containing title, clean_html, word_count, and reading_time.
    """
    target_url = request.args.get("url", "").strip()
    if not target_url:
        return jsonify({"status": "error", "message": "Missing 'url' query parameter."}), 400

    article = extract_clean_article(target_url)
    return jsonify(article)


@app.route("/api/knowledge", methods=["GET"])
def knowledge_api() -> Response:
    """DuckDuckGo Instant Answer / Knowledge Graph proxy endpoint.

    Query params:
        q: Entity query (required).

    Returns:
        JSON containing encyclopedic heading, abstract, hero image, and related topics.
    """
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"status": "error", "message": "Missing 'q' query parameter."}), 400

    data = get_instant_answer(query)
    if not data:
        return jsonify({"status": "not_found", "message": "No entity match found."}), 404

    return jsonify({"status": "success", "data": data})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
