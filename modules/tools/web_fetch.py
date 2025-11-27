import subprocess
import traceback
from urllib.parse import quote_plus

MAX_TEXT_LEN = 150_000

# Python z venv, gdzie jest playwright + readability
PLAYWRIGHT_PY = "/home/hal/HALbridge/.venv_playwright/bin/python"
WEB_TOOL_PATH = "/home/hal/HALbridge/hal_webfetch.py"


def invoke(payload: dict) -> dict:
    url = payload.get("url")
    if not url:
        return {"ok": False, "error": "missing_url"}

    cmd = [PLAYWRIGHT_PY, WEB_TOOL_PATH, url]

    try:
        raw = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        text = raw.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "url": url,
            "text": text[:MAX_TEXT_LEN],
        }
    except subprocess.CalledProcessError as e:
        out = e.output.decode("utf-8", errors="replace") if e.output else ""
        return {
            "ok": False,
            "error": "subprocess_failed",
            "details": out[:2000],
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "trace": traceback.format_exc(),
        }


def resolve_natural_query(text: str) -> str | None:
    if not text:
        return None
    t = text.strip().lower()

    # "otwórz onet"
    if t.startswith(("otwórz ", "otworz ")):
        q = t.split(" ", 1)[1].strip()
        if "." not in q:
            q = q + ".pl"
        if not q.startswith("http"):
            q = "https://" + q
        return q

    # "pokaż stronę xyz.com"
    if "stronę" in t or "strone" in t:
        for w in t.split():
            if "." in w:
                if not w.startswith("http"):
                    w = "https://" + w
                return w

    # "poszukaj / wyszukaj / szukaj ..."
    if any(k in t for k in ("poszukaj", "wyszukaj", "szukaj")):
        return "https://www.bing.com/search?q=" + quote_plus(text)

    return None
