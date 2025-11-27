import sys
import traceback
import re
from playwright.sync_api import sync_playwright
from readability import Document

MAX_TEXT_LEN = 150_000


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"<.*?>", "", s)
    return s


def fetch_rendered_html(url: str) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, timeout=20000)
        page.wait_for_load_state("networkidle")
        html = page.content()
        browser.close()
        return html


def extract_readable(html: str) -> str:
    try:
        doc = Document(html)
        parsed = doc.summary(html_partial=False)
        clean = strip_html(parsed)
        return clean
    except Exception:
        return strip_html(html)


def main() -> None:
    if len(sys.argv) < 2:
        print("Użycie: hal_webfetch.py <URL>", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    try:
        html = fetch_rendered_html(url)
        text = extract_readable(html)
        sys.stdout.write(text[:MAX_TEXT_LEN])
        sys.stdout.flush()
    except Exception as e:
        sys.stderr.write(f"[hal_webfetch ERROR] {e}\n")
        sys.stderr.write(traceback.format_exc())
        sys.stderr.flush()
        sys.exit(2)


if __name__ == "__main__":
    main()
