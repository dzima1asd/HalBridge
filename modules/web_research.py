from __future__ import annotations

import re
from urllib.parse import quote


def _extract_links_from_text(text: str) -> list[dict]:
    links = []
    seen = set()

    for raw in re.findall(r'https?://[^\s<>"\)\]]+', text or ""):
        url = raw.rstrip('.,);]>\'"')
        if url.startswith("http") and url not in seen:
            seen.add(url)
            links.append({"url": url, "title": ""})

    return links[:8]


def _append_sources(answer: str, pages: list[tuple[str, str]]) -> str:
    lines = [(answer or "").strip(), "", "Źródła:"]
    for i, (url, _text) in enumerate(pages[:5], 1):
        lines.append(f"{i}. {url}")
    return "\n".join(lines).strip()


def _normalize_research_query(q: str) -> str:
    raw = (q or "").strip()
    low = raw.lower().strip()

    prefixes = [
        "poszukaj mi informacji o ",
        "poszukaj informacji o ",
        "poszukaj mi info o ",
        "poszukaj info o ",
        "znajdź informacje o ",
        "znajdz informacje o ",
        "wyszukaj informacje o ",
        "sprawdź informacje o ",
        "sprawdz informacje o ",
        "co to jest ",
    ]

    for prefix in prefixes:
        if low.startswith(prefix):
            return raw[len(prefix):].strip()

    return raw


def run_web_research(api, registry, intent: dict, prompt: str) -> str:
    """
    Uniwersalne wyszukiwanie:
    - używa intent["queries"] albo samego promptu,
    - robi search przez Bing,
    - wyciąga URL-e z tekstu wyników,
    - pobiera kilka stron,
    - odpowiada WYŁĄCZNIE na podstawie pobranych stron,
    - jeśli brak źródeł: zwraca brak danych zamiast zgadywać.
    """
    queries = [_normalize_research_query(q) for q in (intent.get("queries") or [prompt])]
    all_links: list[dict] = []

    # 1. Search
    for q in queries[:3]:
        search_url = f"https://www.bing.com/search?q={quote(q)}"
        search_res = registry.invoke("web_fetch", {"url": search_url})
        if not search_res.get("ok"):
            continue

        search_text = (search_res.get("text") or "").strip()
        if not search_text:
            continue

        extracted = _extract_links_from_text(search_text)
        for link in extracted:
            url = (link or {}).get("url") or ""
            title = (link or {}).get("title") or ""
            low_url = url.lower().strip()

            if not url.startswith("http"):
                continue
            if "bing.com/search?" in low_url:
                continue
            if "bing.com/sa/" in low_url:
                continue
            if "r.bing.com" in low_url:
                continue
            if "bing.com/images" in low_url:
                continue

            if url not in [l["url"] for l in all_links]:
                all_links.append({"url": url, "title": title})

    # 2. Fetch pages
    pages: list[tuple[str, str]] = []
    for link in all_links[:5]:
        res = registry.invoke("web_fetch", {"url": link["url"]})
        if not res.get("ok"):
            continue

        text = (res.get("text") or "").strip()
        if not text:
            continue

        pages.append((link["url"], text[:12000]))

    # 3. Hard guard: no sources = no answer
    if not pages:
        return (
            "Nie znalazłem potwierdzonych aktualnych informacji z internetu. "
            "Brak wiarygodnych źródeł, więc nie będę zgadywać."
        )

    # 4. Build source-only context
    context_parts = []
    for i, (url, text) in enumerate(pages, 1):
        context_parts.append(f"ŹRÓDŁO {i}: {url}\n{text}")

    big_context = "\n\n---\n\n".join(context_parts)

    # 5. Final grounded answer
    answer_prompt = (
        "Użytkownik zadał pytanie:\n"
        f"{prompt}\n\n"
        "Masz poniżej treści pobrane z internetu.\n"
        "Zasady bezwzględne:\n"
        "1. Odpowiadaj WYŁĄCZNIE na podstawie źródeł poniżej.\n"
        "2. Jeśli źródła nie potwierdzają czegoś wprost, napisz, że brak potwierdzenia.\n"
        "3. Nie wolno zgadywać ani dopowiadać.\n"
        "4. Na końcu wypisz sekcję 'Źródła:' i podaj użyte URL-e.\n\n"
        + big_context
    )

    answer = api.ask_ai(answer_prompt, execute=False, note="ai_web_answer")
    answer = (answer or "").strip()

    # 6. Hard guard: if model returns empty or forgets sources, append them
    if not answer:
        return _append_sources(
            "Znalazłem źródła, ale nie udało się poprawnie zsyntetyzować odpowiedzi.",
            pages,
        )

    if "Źródła:" not in answer and "Źródła" not in answer:
        answer = _append_sources(answer, pages)

    return answer
