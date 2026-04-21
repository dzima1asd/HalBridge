from __future__ import annotations

import re


def _render_web_result(result) -> str:
    if not isinstance(result, dict):
        return str(result)

    if not result.get("ok", False):
        err = result.get("error") or result.get("message") or "Nieznany błąd"
        return f"❌ {err}"

    url = str(result.get("url", "") or "")
    text = str(result.get("text", "") or "")
    source = str(result.get("source", "") or "")
    used_fallback = bool(result.get("used_fallback", False))
    fallback_reason = str(result.get("fallback_reason", "") or "")

    header = []
    if url:
        header.append(f"🌐 URL: {url}")
    if source:
        src_line = f"📥 Źródło: {source}"
        if used_fallback:
            src_line += " (fallback)"
        header.append(src_line)
    if fallback_reason:
        header.append(f"ℹ️ Powód fallbacku: {fallback_reason}")

    body = text.strip()
    if len(body) > 4000:
        body = body[:4000].rstrip() + "\n...[obcięto]"

    if header and body:
        return "\n".join(header) + "\n\n" + body
    if body:
        return body
    return "\n".join(header) if header else "✅ Brak treści do wyświetlenia"


def handle_browser_runtime(line: str, browser, registry) -> tuple[bool, str | None]:
    if line.startswith("web "):
        url = line[4:].strip()
        result = registry.invoke("web_fetch", {"url": url})
        return True, _render_web_result(result)

    if line.startswith(("otwórz", "pokaż", "znajdź", "wyszukaj")):
        low = line.lower()

        looks_like_fs = (
            any(word in low for word in ["folder", "katalog", "plik", "katalogu", "folderu", "pliku"])
            or any(ch in line for ch in ["/", "\\", "~"])
        )

        looks_like_url = (
            "http://" in low
            or "https://" in low
            or "www." in low
            or "stronę" in low
            or "strone" in low
            or "strona " in low
            or bool(re.search(r"\.[a-z]{2,4}(/|$|\s)", low))
        )

        browserish_query = (
            "youtube" in low
            or "film" in low
            or "teledysk" in low
            or "grafika" in low
            or "obrazy" in low
            or "zdjęcia" in low
        )

        if not looks_like_fs and (looks_like_url or browserish_query):
            return True, browser.open(line)

    return False, None
