import os
import json
import urllib.parse
import urllib.request


BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

if not BRAVE_API_KEY:
    raise RuntimeError("Brave API Key not found in environment variable BRAVE_API_KEY.")

MAX_SUMMARY_CHARS = 250
MAX_RESULTS = 5
MAX_ARTICLE_CHARS = 1200


# ============================================================
#  BRAVE NEWS SEARCH ENGINE (JSON API)
# ============================================================

class BraveSearchEngine:
    def __init__(self):
        self.url = "https://api.search.brave.com/res/v1/web/search"

    def search(self, query: str):
        params = urllib.parse.urlencode({
            "q": query,
            "count": MAX_RESULTS
        })
        full_url = f"{self.url}?{params}"

        req = urllib.request.Request(
            full_url,
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": BRAVE_API_KEY,
                "User-Agent": "Mozilla/5.0"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                data = r.read().decode("utf-8", errors="ignore")
                parsed = json.loads(data)
        except Exception:
            return []

        out = []
        web_results = parsed.get("web", {}).get("results", [])

        for item in web_results:
            url = item.get("url")
            title = item.get("title")
            if url and title:
                out.append({"url": url, "title": title})

        return out[:MAX_RESULTS]


# ============================================================
#  FETCH + SUMMARY
# ============================================================

class PageFetcher:
    def __init__(self, registry, api):
        self.registry = registry
        self.api = api

    def _summarize(self, text: str) -> str:
        cut = text[:MAX_ARTICLE_CHARS]
        if not cut:
            return ""

        prompt = (
            f"Streść ten artykuł w maksymalnie {MAX_SUMMARY_CHARS} znakach. "
            "Podaj tylko fakty, 3–5 zdań:\n\n" + cut
        )

        summary = self.api.ask_ai(prompt, execute=False, note="summary")
        summary = (summary or "").strip()

        if len(summary) > MAX_SUMMARY_CHARS:
            summary = summary[:MAX_SUMMARY_CHARS]

        return summary

    def fetch(self, links, limit=3):
        out = []
        for link in links[:limit]:
            res = self.registry.invoke("web_fetch", {"url": link["url"]})
            if not res.get("ok"):
                continue

            text = res.get("text") or ""
            if not text:
                continue

            summary = self._summarize(text)
            if not summary:
                continue

            out.append({
                "url": link["url"],
                "title": link["title"],
                "text": summary
            })

        return out


# ============================================================
#  CONTEXT BUILDER
# ============================================================

class ContextBuilder:
    def build(self, pages, prompt):
        out = [
            "Odpowiadasz tylko na podstawie poniższych streszczeń.\n"
            "Jeśli czegoś nie ma w źródłach — powiedz 'brak danych'.\n\n",
            f"PYTANIE:\n{prompt}\n\n",
            "ŹRÓDŁA:\n"
        ]

        for i, pg in enumerate(pages, 1):
            out.append(
                f"\n===== ŹRÓDŁO {i}: {pg['title']} ({pg['url']}) =====\n{pg['text']}\n"
            )

        return "".join(out)


# ============================================================
#  ORCHESTRATOR
# ============================================================

class WebOrchestrator:
    def __init__(self, api, registry):
        self.registry = registry
        self.api = api
        self.engine = BraveSearchEngine()
        self.fetcher = PageFetcher(self.registry, self.api)
        self.builder = ContextBuilder()

    def run(self, query: str) -> dict:
        links = self.engine.search(query)
        if not links:
            return {"ok": False, "reason": "no_links"}

        pages = self.fetcher.fetch(links, limit=1)
        if not pages:
            return {"ok": False, "reason": "no_content", "links": links}

        context = self.builder.build(pages, query)

        return {"ok": True, "context": context, "pages": pages}
