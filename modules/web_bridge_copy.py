import subprocess
import shlex
from urllib.parse import quote_plus

# Ścieżki do venv Playwright i skryptu hal_webfetch.py
PLAYWRIGHT_PY = "/home/hal/HALbridge/.venv_playwright/bin/python"
WEB_TOOL_PATH = "/home/hal/HALbridge/hal_webfetch.py"


def fetch_url(url: str) -> str:
    """
    Uruchamia Playwright przez hal_webfetch.py i zwraca HTML jako tekst.
    Używane jako niskopoziomowy fetcher.
    """
    cmd = [PLAYWRIGHT_PY, WEB_TOOL_PATH, url]
    try:
        out = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        return out.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[WEB ERROR] {e}"


def web_fetch(url: str) -> str:
    """
    Główna fasada używana przez agenta oraz registry
    (narzędzie 'web_fetch').
    """
    return fetch_url(url)


def resolve_natural_query(text: str) -> str | None:
    """
    Próbuje wykryć zapytanie webowe z języka naturalnego.

    Przykłady:
    - 'otwórz onet'
    - 'otworz onet'
    - 'pokaż stronę wp.pl'
    - 'poszukaj newsów w internecie'
    - 'wyszukaj coś tam w Google'

    Zwraca pełny URL lub None.
    """
    if not text:
        return None

    t = text.strip().lower()

    # --- "otwórz onet" / "otworz onet" ---
    if t.startswith("otwórz ") or t.startswith("otworz "):
        q = t.split(" ", 1)[1].strip()
        if not q:
            return None
        # jeśli bez kropki – domyślnie .pl
        if "." not in q:
            q = q + ".pl"
        # jeśli bez protokołu – dodaj https://
        if not q.startswith("http://") and not q.startswith("https://"):
            q = "https://" + q
        return q

    # --- "pokaż stronę ..." / "pokaz strone ..." ---
    if "stronę" in t or "strone" in t:
        for w in t.split():
            if "." in w:
                q = w.strip(",.;:()[]{}")
                if not q:
                    continue
                if not q.startswith("http://") and not q.startswith("https://"):
                    q = "https://" + q
                return q

    # --- "poszukaj / wyszukaj / szukaj ..." → bing search ---
    if any(k in t for k in ("poszukaj", "wyszukaj", "szukaj")):
        # Używamy ORYGINALNEGO tekstu, nie tylko zlowerowanego
        q = text.strip()
        if not q:
            return None
        return "https://www.bing.com/search?q=" + quote_plus(q)

    return None
