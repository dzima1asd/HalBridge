#!/usr/bin/env python3
# Lightweight helper: używany przez agenta do pobierania treści stron przez Playwright

from playwright.sync_api import sync_playwright
import sys

def main():
    if len(sys.argv) < 2:
        print("USAGE: browser_helper.py URL", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        title = page.title()
        try:
            body = page.inner_text("body")
        except Exception:
            body = ""
        browser.close()

    print("TITLE:", title)
    print("-----")
    # trochę przycinamy, żeby nie zalać logów
    if len(body) > 8000:
        body = body[:8000] + "\n...[TRUNCATED]..."
    print(body)

if __name__ == "__main__":
    main()
