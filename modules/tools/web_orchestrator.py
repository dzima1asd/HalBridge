from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from typing import Any
from modules.source_policy import get_source_policy

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY")

MAX_RESULTS_PER_QUERY = 8
MAX_FETCH_PAGES = 6
MAX_PAGE_CHARS = 1800


def _ensure_brave_api_key() -> None:
    if not BRAVE_API_KEY:
        raise RuntimeError("Brave API Key not found in environment variable BRAVE_API_KEY.")


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def detect_domain(query: str, route: str | None = None) -> str:
    q = _norm(query)

    politics_hints = [
        "premier", "prezydent", "minister", "marszał", "wojewod", "rząd", "rzad",
        "sejm", "senat", "prezes rady ministrów", "prezes rady ministrow",
        "gabinet", "administracja", "wiceprezydent", "zastępc", "zastepc"
    ]
    fiction_hints = [
        "smurf", "smurfów", "smurfow", "smerf", "smerfów", "smerfow",
        "hogwart", "harry potter", "star wars", "marvel", "batman", "superman"
    ]
    local_city_hints = [
        "białystok", "bialystok", "warszawa", "kraków", "krakow", "gdańsk", "gdansk",
        "wrocław", "wroclaw", "lublin", "poznań", "poznan", "szczecin", "olsztyn"
    ]
    recency_hints = [
        "co nowego", "dziś", "dzis", "dzisiaj", "ostatnio", "aktualności", "aktualnosci",
        "wiadomości", "wiadomosci", "wydarzyło", "wydarzylo", "najnowsze", "today"
    ]

    if any(x in q for x in fiction_hints):
        return "fiction_popculture"

    if route == "current_facts" or any(x in q for x in politics_hints):
        return "politics_public_office"

    if route == "news_research" and any(x in q for x in local_city_hints):
        return "local_news"

    if route == "news_research" or any(x in q for x in recency_hints):
        return "general_news"

    return "general_reference"



def extract_city_hint(query: str) -> str | None:
    q = _norm(query)
    city_map = {
        "białystok": "Białystok",
        "bialystok": "Białystok",
        "warszawa": "Warszawa",
        "kraków": "Kraków",
        "krakow": "Kraków",
        "gdańsk": "Gdańsk",
        "gdansk": "Gdańsk",
        "wrocław": "Wrocław",
        "wroclaw": "Wrocław",
        "poznań": "Poznań",
        "poznan": "Poznań",
        "lublin": "Lublin",
        "olsztyn": "Olsztyn",
        "szczecin": "Szczecin",
    }
    for key, val in city_map.items():
        if key in q:
            return val
    return None


def expand_policy_queries(query: str, domain: str, route: str | None = None, policy: dict[str, Any] | None = None) -> list[str]:
    q = query.strip()
    qn = _norm(q)
    policy = policy or {}
    loc = policy.get("location")
    policy_name = policy.get("policy_name")
    extra = []

    city_display = {
        "białystok": "Białystok",
        "bialystok": "Białystok",
        "poznań": "Poznań",
        "poznan": "Poznań",
        "warszawa": "Warszawa",
        "kraków": "Kraków",
        "krakow": "Kraków",
        "gdańsk": "Gdańsk",
        "gdansk": "Gdańsk",
        "wrocław": "Wrocław",
        "wroclaw": "Wrocław",
    }

    if policy_name == "local_news_generic" and loc:
        city = city_display.get(loc, str(loc).title())
        extra += [
            f"{city} aktualności",
            f"{city} wiadomości",
            f"{city} wydarzenia dziś",
            f"{city} wydarzenia dzisiaj",
            f"{city} portal miejski aktualności",
            f"{city} co słychać",
        ]

    if policy_name == "current_facts_us_or_global":
        if any(x in qn for x in ["trump", "zastępc", "zastepc", "wiceprezydent", "vice president"]):
            extra += [
                "Trump vice president",
                "Vice President of the United States",
                "Trump running mate",
                "current vice president usa",
            ]

    if policy_name == "current_facts_pl":
        if any(x in qn for x in ["premier", "prezydent", "minister", "rząd", "rzad"]):
            extra += [
                "Premier Polski gov.pl",
                "Prezes Rady Ministrów gov.pl",
                "Rada Ministrów gov.pl",
            ]

    uniq = []
    seen = set()
    for item in extra:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq

def build_search_queries(query: str, domain: str, route: str | None = None, policy: dict[str, Any] | None = None) -> list[str]:
    q = query.strip()
    out = [q]
    city = extract_city_hint(q)
    policy = policy or {}
    preferred_domains = policy.get("preferred_domains", []) or []

    for extra_q in expand_policy_queries(q, domain, route, policy):
        out.append(extra_q)

    for dom in preferred_domains:
        out.append(f"{q} site:{dom}")

    if domain == "politics_public_office":
        out += [
            f"{q} site:gov.pl",
            f"{q} site:prezydent.pl",
            f"{q} site:sejm.gov.pl",
            f"{q} site:wikipedia.org",
        ]

    elif domain == "fiction_popculture":
        out += [
            f"{q} fandom",
            f"{q} wiki",
            f"{q} wikipedia",
        ]

    elif domain == "local_news":
        city_q = city or q
        out += [
            f"{city_q} aktualności",
            f"{city_q} wiadomości",
            f"{city_q} wydarzenia dziś",
            f"{city_q} portal miejski aktualności",
            f"{city_q} dziś lokalne wiadomości",
        ]

        if city == "Białystok":
            out += [
                "Białystok aktualności site:bialystokonline.pl",
                "Białystok wiadomości site:poranny.pl",
                "Białystok wiadomości site:radio.bialystok.pl",
                "Białystok aktualności site:wrotapodlasia.pl",
                "Białystok dziś site:bialystokonline.pl",
            ]

    elif domain == "general_news":
        out += [
            f"{q} news",
            f"{q} aktualności",
            f"{q} dzisiaj",
        ]

    else:
        out += [
            f"{q} wikipedia",
            f"{q} definicja",
        ]

    uniq = []
    seen = set()
    for item in out:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(item)
    return uniq[:8]



def direct_source_urls(policy: dict[str, Any] | None = None) -> list[dict[str, str]]:
    policy = policy or {}
    out = []
    for dom in policy.get("preferred_domains", []) or []:
        dom = (dom or "").strip()
        if not dom:
            continue
        url = f"https://{dom}"
        out.append({
            "url": url,
            "title": f"Direct source: {dom}",
            "search_query": "__direct__",
        })
    return out

def _host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def source_score(url: str, title: str, domain: str, policy: dict[str, Any] | None = None) -> int:
    host = _host(url)
    title_l = (title or "").lower()
    score = 0
    policy = policy or {}
    preferred_domains = policy.get("preferred_domains", []) or []

    if any(host.endswith(dom) or dom in host for dom in preferred_domains):
        score += 120

    if domain == "politics_public_office":
        if host.endswith("gov.pl") or host.endswith("prezydent.pl") or host.endswith("sejm.gov.pl") or host.endswith("senat.gov.pl"):
            score += 100
        if "wikipedia.org" in host:
            score += 40
        if any(x in host for x in ["tvn24.pl", "rp.pl", "polsatnews.pl", "pap.pl", "onet.pl", "interia.pl", "wp.pl"]):
            score += 20

    elif domain == "fiction_popculture":
        if "fandom.com" in host or "wikia.com" in host:
            score += 100
        if "wikipedia.org" in host:
            score += 35

    elif domain == "local_news":
        if any(x in host for x in ["bialystokonline.pl", "poranny.pl", "radio.bialystok.pl", "wrotapodlasia.pl"]):
            score += 90
        elif host.endswith(".pl"):
            score += 15

        if any(x in title_l for x in ["białystok", "bialystok", "wydarzenia", "aktualności", "aktualnosci", "wiadomości", "wiadomosci", "dziś", "dzis"]):
            score += 20

        if any(x in title_l for x in ["cookie", "prywatności", "prywatnosci", "regulamin", "zgody"]):
            score -= 80

    elif domain == "general_news":
        if any(x in host for x in ["pap.pl", "tvn24.pl", "rp.pl", "onet.pl", "interia.pl", "wp.pl", "polsatnews.pl", "money.pl"]):
            score += 50
        if "wikipedia.org" in host:
            score += 5

    else:
        if "wikipedia.org" in host:
            score += 30

    if any(x in host for x in ["facebook.com", "instagram.com", "tiktok.com", "youtube.com", "pinterest.", "reddit.com"]):
        score -= 40

    return score


def looks_like_garbage(title: str, text: str) -> bool:
    blob = ((title or "") + " " + (text or "")).lower()
    bad = [
        "cookie", "cookies", "prywatności", "prywatnosci", "privacy", "consent",
        "zgadzam się", "zgadzam sie", "ustawienia prywatności", "ustawienia prywatnosci",
        "zarządzaj zgodą", "zarzadzaj zgoda", "wyraź zgodę", "wyraz zgode",
        "ta strona wykorzystuje pliki cookie", "używamy plików cookie", "uzywamy plikow cookie",
    ]
    if any(x in blob for x in bad):
        return True

    meaningful = len((text or "").strip())
    if meaningful < 220:
        return True

    return False


def clean_text(text: str) -> str:
    t = text or ""
    t = re.sub(r"\s+", " ", t).strip()
    return t[:MAX_PAGE_CHARS]


class BraveSearchEngine:
    def __init__(self):
        self.url = "https://api.search.brave.com/res/v1/web/search"

    def _single_search(self, query: str) -> list[dict[str, str]]:
        _ensure_brave_api_key()
        params = urllib.parse.urlencode({"q": query, "count": MAX_RESULTS_PER_QUERY})
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
            with urllib.request.urlopen(req, timeout=12) as r:
                parsed = json.loads(r.read().decode("utf-8", errors="ignore"))
        except Exception:
            return []

        out = []
        for item in parsed.get("web", {}).get("results", []):
            url = item.get("url")
            title = item.get("title")
            description = item.get("description") or item.get("snippet") or ""
            if url and title:
                out.append({
                    "url": url,
                    "title": title,
                    "description": description,
                    "search_query": query
                })
        return out

    def search(self, query: str, domain: str, route: str | None = None, policy: dict[str, Any] | None = None) -> tuple[list[dict[str, str]], list[str]]:
        planned = build_search_queries(query, domain, route, policy)
        merged: dict[str, dict[str, str]] = {}

        for q in planned:
            for item in self._single_search(q):
                url = item["url"]
                old = merged.get(url)
                if old is None:
                    merged[url] = item
                else:
                    old["_hits"] = old.get("_hits", 1) + 1

        items = list(merged.values())
        items.sort(
            key=lambda x: (
                source_score(x["url"], x.get("title", ""), domain, policy) + int(x.get("_hits", 1)) * 5
            ),
            reverse=True,
        )
        return items[:8], planned


class PageFetcher:
    def __init__(self, registry, api):
        self.registry = registry
        self.api = api

    def fetch(self, links: list[dict[str, str]], limit: int = MAX_FETCH_PAGES) -> list[dict[str, str]]:
        out = []
        for link in links[:limit]:
            try:
                res = self.registry.invoke("web_fetch", {"url": link["url"]})
            except Exception:
                continue

            if not res.get("ok"):
                continue

            text = clean_text(res.get("text") or "")
            title = link.get("title", "")

            if not text:
                continue
            if looks_like_garbage(title, text):
                continue

            out.append({
                "url": link["url"],
                "title": title,
                "text": text,
            })

        return out



def build_search_only_context(links: list[dict[str, str]], prompt: str, domain: str, planned_queries: list[str]) -> str:
    out = [
        "Odpowiadasz tylko na podstawie poniższych wyników wyszukiwania.\n",
        "Nie zgaduj. Jeśli wyników nie wystarcza do pewnej odpowiedzi, napisz dokładnie: 'Brak danych.'.\n\n",
        f"DOMENA: {domain}\n",
        f"PYTANIE:\n{prompt}\n\n",
        "PLAN ZAPYTAŃ:\n",
    ]

    for q in planned_queries:
        out.append(f"- {q}\n")

    out.append("\nWYNIKI WYSZUKIWANIA:\n")

    for i, item in enumerate(links[:5], 1):
        title = item.get("title", "brak tytułu")
        url = item.get("url", "")
        desc = item.get("description", "") or ""
        out.append(f"\n===== WYNIK {i}: {title} ({url}) =====\n")
        if desc:
            out.append(desc + "\n")

    return "".join(out)

class ContextBuilder:
    def build(self, pages: list[dict[str, str]], prompt: str, domain: str, planned_queries: list[str]) -> str:
        out = [
            "Odpowiadasz tylko na podstawie poniższych źródeł.\n",
            "Jeśli czegoś nie ma w źródłach — powiedz 'brak danych'.\n",
            "Nie zgaduj. Nie używaj wiedzy spoza źródeł.\n\n",
            f"DOMENA: {domain}\n",
            f"PYTANIE:\n{prompt}\n\n",
            "PLAN ZAPYTAŃ:\n",
        ]

        for q in planned_queries:
            out.append(f"- {q}\n")

        out.append("\nŹRÓDŁA:\n")

        for i, pg in enumerate(pages, 1):
            out.append(f"\n===== ŹRÓDŁO {i}: {pg['title']} ({pg['url']}) =====\n{pg['text']}\n")

        return "".join(out)


class WebOrchestrator:
    def __init__(self, api, registry):
        self.registry = registry
        self.api = api
        self.engine = BraveSearchEngine()
        self.fetcher = PageFetcher(self.registry, self.api)
        self.builder = ContextBuilder()

    def run(self, query: str, route: str | None = None) -> dict[str, Any]:
        debug: dict[str, Any] = {
            "query": query,
            "route": route,
        }

        try:
            domain = detect_domain(query, route)
            debug["domain"] = domain
            policy = get_source_policy(query, route, domain)
            debug["policy"] = policy

            direct_links = []
            direct_pages = []

            if policy.get("policy_name") != "local_news_generic":
                direct_links = direct_source_urls(policy)
                debug["direct_links_count"] = len(direct_links)
                debug["direct_links_preview"] = [
                    {"title": x.get("title", ""), "url": x.get("url", "")}
                    for x in direct_links[:5]
                ]

                direct_pages = self.fetcher.fetch(direct_links, limit=min(MAX_FETCH_PAGES, len(direct_links))) if direct_links else []
                debug["direct_pages_count"] = len(direct_pages)
                debug["direct_pages_preview"] = [
                    {
                        "title": x.get("title", ""),
                        "url": x.get("url", ""),
                        "text_len": len(x.get("text", "") or ""),
                        "text_preview": (x.get("text", "") or "")[:220],
                    }
                    for x in direct_pages[:5]
                ]
            else:
                debug["direct_links_count"] = 0
                debug["direct_links_preview"] = []
                debug["direct_pages_count"] = 0
                debug["direct_pages_preview"] = []

            links, planned = self.engine.search(query, domain, route, policy)
            debug["planned_queries"] = planned
            debug["search_links_count"] = len(links)
            debug["search_links_preview"] = [
                {"title": x.get("title", ""), "url": x.get("url", "")}
                for x in links[:5]
            ]
        except Exception as e:
            return {
                "ok": False,
                "reason": f"search_error: {type(e).__name__}: {e}",
                "debug": debug,
            }

        if not links and not direct_pages:
            return {
                "ok": False,
                "reason": "no_links",
                "domain": domain,
                "queries": [],
                "debug": debug,
            }

        pages = list(direct_pages)

        preferred_domains = policy.get("preferred_domains", []) or []
        preferred_links = []
        other_links = []

        for link in links:
            url = (link.get("url") or "").lower()
            if any(dom in url for dom in preferred_domains):
                preferred_links.append(link)
            else:
                other_links.append(link)

        debug["preferred_search_links_count"] = len(preferred_links)
        debug["other_search_links_count"] = len(other_links)

        if len(pages) < MAX_FETCH_PAGES and preferred_links:
            pref_pages = self.fetcher.fetch(preferred_links, limit=MAX_FETCH_PAGES)
            seen = {x.get("url") for x in pages}
            for pg in pref_pages:
                if pg.get("url") not in seen:
                    pages.append(pg)
                    seen.add(pg.get("url"))
                if len(pages) >= MAX_FETCH_PAGES:
                    break

        if len(pages) < MAX_FETCH_PAGES and other_links:
            extra_pages = self.fetcher.fetch(other_links, limit=MAX_FETCH_PAGES)
            seen = {x.get("url") for x in pages}
            for pg in extra_pages:
                if pg.get("url") not in seen:
                    pages.append(pg)
                    seen.add(pg.get("url"))
                if len(pages) >= MAX_FETCH_PAGES:
                    break
        debug["pages_count"] = len(pages)
        debug["pages_preview"] = [
            {
                "title": x.get("title", ""),
                "url": x.get("url", ""),
                "text_len": len(x.get("text", "") or ""),
                "text_preview": (x.get("text", "") or "")[:220],
            }
            for x in pages[:5]
        ]

        if not pages:
            search_only_links = links[:5]
            context = build_search_only_context(search_only_links, query, domain, planned)
            debug["used_search_only_context"] = True
            debug["search_only_context_len"] = len(context)
            return {
                "ok": True,
                "reason": "search_only_context",
                "domain": domain,
                "queries": planned,
                "links": search_only_links,
                "context": context,
                "pages": [],
                "debug": debug,
            }

        context = self.builder.build(pages, query, domain, planned)
        debug["context_len"] = len(context)

        return {
            "ok": True,
            "domain": domain,
            "queries": planned,
            "context": context,
            "pages": pages,
            "debug": debug,
        }
