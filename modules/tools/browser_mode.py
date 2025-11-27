"""
browser_query: narzędzie udające browser-mode.
Zwraca analizę strony, tytuł i linki.
"""

from bs4 import BeautifulSoup
import re

def perform_browser_query(url: str, html: str):
    soup = BeautifulSoup(html, "html.parser")

    title = soup.title.string.strip() if soup.title else "(brak tytułu)"

    # wyciąganie linków
    links = []
    for a in soup.find_all("a"):
        txt = a.get_text(strip=True) or "(bez tekstu)"
        href = a.get("href", "")
        if href:
            links.append({"text": txt, "href": href})

    return {
        "title": title,
        "links": links,
        "summary": summarize_text(soup.get_text())
    }

def summarize_text(text: str):
    clean = re.sub(r"\s+", " ", text).strip()
    return clean[:2000]
