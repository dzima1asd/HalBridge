import subprocess
import traceback
import urllib.request
from urllib.parse import quote_plus

MAX_TEXT_LEN = 150_000

# Python z venv, gdzie jest playwright + readability
PLAYWRIGHT_PY = "/home/hal/HALbridge/.venv_playwright/bin/python"
WEB_TOOL_PATH = "/home/hal/HALbridge/hal_webfetch.py"


def _fetch_with_urllib(url: str) -> str:
    """
    Fallback: zwykłe pobranie strony z nagłówkiem User-Agent,
    żeby wyszukiwarki nie traktowały nas jak bota z epoki kamienia łupanego.
    """
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/119.0 Safari/537.36"
            )
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
            try:
                return data.decode("utf-8", errors="ignore")
            except Exception:
                return data.decode("latin1", errors="ignore")
    except Exception:
        return ""


def invoke(payload: dict) -> dict:
    url = payload.get("url")
    if not url:
        return {"ok": False, "error": "missing_url"}

    cmd = [PLAYWRIGHT_PY, WEB_TOOL_PATH, url]

    # 1) Najpierw próbujemy hal_webfetch (playwright + readability)
    try:
        raw = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=30,
        )
        text = raw.decode("utf-8", errors="replace").strip()

        # Jeśli coś faktycznie przyszło → używamy
        if text:
            return {
                "ok": True,
                "url": url,
                "text": text[:MAX_TEXT_LEN],
            }

        # Jeśli hal_webfetch zwrócił pustkę → lecimy fallbackiem
        html = _fetch_with_urllib(url).strip()
        if html:
            return {
                "ok": True,
                "url": url,
                "text": html[:MAX_TEXT_LEN],
            }

        # Pusto po obu próbach
        return {
            "ok": False,
            "error": "empty_content",
            "details": "hal_webfetch empty & urllib empty",
        }

    except subprocess.CalledProcessError as e:
        out = e.output.decode("utf-8", errors="replace") if e.output else ""

        # Przy błędzie subprocessu też próbujemy fallback
        html = _fetch_with_urllib(url).strip()
        if html:
            return {
                "ok": True,
                "url": url,
                "text": html[:MAX_TEXT_LEN],
            }

        return {
            "ok": False,
            "error": "subprocess_failed",
            "details": out[:2000],
        }

    except Exception as e:
        # Awaria totalna subprocessu → ostatnia próba: urllib
        html = _fetch_with_urllib(url).strip()
        if html:
            return {
                "ok": True,
                "url": url,
                "text": html[:MAX_TEXT_LEN],
            }

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
