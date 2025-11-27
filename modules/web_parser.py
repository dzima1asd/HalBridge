from bs4 import BeautifulSoup
import re

def score_node(node):
    """Heurystyka content-density: ile słów w stosunku do długości HTML."""
    text = node.get_text(" ", strip=True)
    if not text:
        return 0
    words = len(text.split())
    html_len = len(str(node))
    return words / max(html_len, 1)

def extract_main_content(soup):
    """Znajdź najbardziej treściowy blok."""
    candidates = soup.find_all(["article", "section", "div", "main"])
    if not candidates:
        return soup

    best = max(candidates, key=score_node)
    return best

def remove_noise(soup):
    """Usuń typowe internetowe śmieci."""
    noise_tags = ["script", "style", "noscript", "svg", "canvas", "iframe", "header", "footer"]
    for tag in soup(noise_tags):
        tag.decompose()

    # Usunięcie reklam, sidebarów i widgetów
    junk_keywords = [
        "cookie", "banner", "advert", "promo", "newsletter", "subscribe",
        "sidebar", "share", "social", "toolbar", "comment", "related",
        "popup", "modal", "tracking", "signin", "login"
    ]

    for tag in soup.find_all(True):
        class_str = " ".join(tag.get("class", [])).lower()
        id_str = (tag.get("id") or "").lower()
        if any(j in class_str for j in junk_keywords):
            tag.decompose()
            continue
        if any(j in id_str for j in junk_keywords):
            tag.decompose()
            continue

def render_text(node):
    """Konwertuje HTML na czysty tekst z zachowaniem akapitów i nagłówków."""
    lines = []

    for elem in node.descendants:
        if elem.name in ["h1", "h2", "h3"]:
            title = elem.get_text(" ", strip=True)
            if title:
                lines.append(f"\n# {title} #\n")

        elif elem.name in ["p", "li"]:
            txt = elem.get_text(" ", strip=True)
            if txt:
                lines.append(txt)

    # Jeżeli w tekście nie ma paragrafów, weź całość
    if not lines:
        full = node.get_text(" ", strip=True)
        return full

    # Normalizacja i łączenie
    cleaned = []
    for line in lines:
        line = re.sub(r"\s+", " ", line.strip())
        if line:
            cleaned.append(line)

    return "\n".join(cleaned)

def parse_html(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")

        remove_noise(soup)
        main = extract_main_content(soup)
        text = render_text(main)

        # Usunięcie śmieciowych linijek
        junk_words = ["share", "tweet", "cookies", "login"]
        final = []
        for line in text.split("\n"):
            if any(j in line.lower() for j in junk_words):
                continue
            final.append(line)

        return "\n".join(final)

    except Exception as e:
        return f"[web_parser error] {e}"
