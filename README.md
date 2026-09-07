# ⚡ SOUL Search Engine

A hyper-fast, privacy-first meta-search engine featuring **Dual-Channel Live Web Search**, **Smart Community Reranking** (Reddit/GitHub boost), **DuckDuckGo Knowledge Graph** entity cards, and an in-page **1-Click Clean Reader** that strips ads and popups.

---

## ✨ Features

- 🌐 **Live Real-Time Web Search:** Queries the live open web via DuckDuckGo's live backend with zero latency, zero crawler overhead, and zero database required.
- 💬 **Smart Community & Human Reranker:** Automatically elevates real human discussions (Reddit, Hacker News, GitHub, Stack Overflow) by **+45%** so authentic answers appear at the top instead of SEO marketing spam.
- 🏛 **DuckDuckGo Knowledge Graph:** Rich entity panels displaying official encyclopedic summaries, hero images, and interactive related-topic pivot tags.
- 📖 **1-Click Clean Reader View:** Built-in distraction-free reader mode that extracts clean article text, headings, and images while stripping ads, cookie banners, and paywalls.
- ✍️ **AI Spell-Check:** Google Gemini Flash integration for query typo and spelling correction (`Did you mean: ...`).
- 🎨 **Modern Dark-Mode UI:** Frosted glass aesthetic, liquid thermal accents, and category filter tabs (`All` vs `Discussions & Reddit`).

---

## 🚀 Quick Start

### 1. Install Dependencies
```bash
pip install Flask ddgs requests beautifulsoup4 google-genai
```

### 2. (Optional) Set Gemini API Key
```bash
export GEMINI_API_KEY="your_api_key_here"
```
*(Search works completely fine even without an API key!)*

### 3. Run the Search Engine
```bash
python main.py
```
Open **[http://localhost:5000](http://localhost:5000)** in your browser!

---

## 📡 API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Main web search UI |
| `/api/search?q=<query>&mode=<all\|discussions>` | `GET` | JSON search results with Knowledge Panel |
| `/api/reader?url=<url>` | `GET` | Distraction-free clean article reader |
| `/api/knowledge?q=<query>` | `GET` | DuckDuckGo Instant Answer entity details |

---

## 📄 License
MIT License.
