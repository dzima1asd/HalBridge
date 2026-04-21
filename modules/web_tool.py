# LEGACY / DO NOT EXTEND
# ------------------------------------------------------------
# Ten plik jest starszą, uproszczoną wersją fetchera webowego.
# Nie stanowi oficjalnej ścieżki runtime HALbridge.
#
# Aktualna ścieżka kanoniczna:
# - modules/tools/web_fetch.py
# - hal_webfetch.py
# - modules/tools/browser_query.py
#
# Status:
# - legacy
# - nie rozwijać
# - nie podpinać do nowego server_api
# ------------------------------------------------------------

import sys
from playwright.sync_api import sync_playwright

def fetch_url(url: str) -> str:
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=15000)
            text = page.content()
            browser.close()
            return text
    except Exception as e:
        return f"[web_tool error] {e}"

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("[web_tool] usage: python3 web_tool.py <URL>")
        sys.exit(1)
    print(fetch_url(sys.argv[1]))
