# ⚡ Light Search Engine

Built and maintained by **[Nishkarsh Shrivastava (szzsuke)](https://github.com/szzsuke)**.

🌐 **Live Experience:** [**https://szzsuke.github.io/Light-Search-Engine/**](https://szzsuke.github.io/Light-Search-Engine/)

---

## ✨ Key Features

- 🌌 **Living 3D Stage:** Interactive Three.js particle backdrop with custom shader search and audio controls.
- 🛡️ **Interactive Safe Search:** Instant switch toggle on results to effortlessly transition between safe and unfiltered (NSFW / SFW) surfing.
- 🔍 **Real-Time Meta Search:** Deep multi-source retrieval blending web results, domain collapsing, and Reddit discussions with zero crawler overhead.
- ⚡ **Instant Predictive Autocomplete & Related Chips:** Fast prefix suggestions (`/api/suggest`) and clickable related search chips.
- 🏛️ **Knowledge Graph & Creator Panel:** Rich entity panels and a dedicated profile card when querying `szzsuke` or `nishkarsh`.
- 🎵 **Integrated Ambient Soundtrack:** Built-in audio controller featuring *Evan Call - Time Flows Ever Onward*.
- 📖 **1-Click Clean Reader Mode:** Distraction-free article extraction stripping ads, banners, and paywalls (`/api/reader`).

---

## 🌐 GitHub Pages Deployment

The frontend experience is deployed via **GitHub Actions**:

🔗 **[https://szzsuke.github.io/Light-Search-Engine/](https://szzsuke.github.io/Light-Search-Engine/)**

### To Enable on GitHub:
1. Navigate to your repository **Settings** &rarr; **Pages**.
2. Under **Build and deployment** &rarr; **Source**, select **GitHub Actions**.
3. The workflow in `.github/workflows/deploy-pages.yml` will automatically build and publish your site!

---

## 🚀 Local Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. (Optional) Set Gemini API Key
```bash
export GEMINI_API_KEY="your_api_key_here"
```
*(Search works completely fine even without an API key!)*

### 3. Start the Server
```bash
python main.py
```
Open **[http://localhost:5000](http://localhost:5000)** in your browser!

---

## 📡 API Endpoints

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/` | `GET` | Main interactive search engine frontend |
| `/api/search?q=<query>&tab=<all\|images\|news\|videos>&safe=<1\|0>&offset=<n>` | `GET` | JSON search results with Knowledge Panel & pagination |
| `/api/suggest?q=<query>` | `GET` | Predictive domain completions and search queries |
| `/api/reader?url=<url>` | `GET` | Distraction-free clean article reader |
| `/api/knowledge?q=<query>` | `GET` | Instant answer entity knowledge graph |

---

## 📄 License
MIT License. Open source under the terms of the MIT License.
