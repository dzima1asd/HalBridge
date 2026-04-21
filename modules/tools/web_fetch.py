import subprocess
import urllib.request
from urllib.parse import quote_plus

from modules.web_settings import playwright_python, hal_webfetch_path

MAX_TEXT_LEN = 150_000
SUBPROCESS_TIMEOUT = 12


def _fetch_with_urllib(url: str) -> str:
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

    cmd = [playwright_python(), hal_webfetch_path(), url]

    try:
        raw = subprocess.check_output(
            cmd,
            stderr=subprocess.STDOUT,
            timeout=SUBPROCESS_TIMEOUT,
        )
        text = raw.decode("utf-8", errors="replace").strip()

        if text:
            return {
                "ok": True,
                "url": url,
                "text": text[:MAX_TEXT_LEN],
                "source": "hal_webfetch",
                "used_fallback": False,
            }

    except subprocess.TimeoutExpired as e:
        details = f"timeout after {SUBPROCESS_TIMEOUT}s"
    except subprocess.CalledProcessError as e:
        details = e.output.decode("utf-8", errors="replace")[:2000] if e.output else "subprocess failed"
    except Exception as e:
        details = f"{type(e).__name__}: {e}"
    else:
        details = "hal_webfetch returned empty output"

    html = _fetch_with_urllib(url).strip()
    if html:
        return {
            "ok": True,
            "url": url,
            "text": html[:MAX_TEXT_LEN],
            "source": "urllib_fallback",
            "used_fallback": True,
            "fallback_reason": details,
        }

    return {
        "ok": False,
        "error": "web_fetch_failed",
        "url": url,
        "details": details,
    }


def resolve_natural_query(query: str) -> str:
    q = (query or "").strip()
    if q.startswith("http://") or q.startswith("https://"):
        return q
    return f"https://www.bing.com/search?q={quote_plus(q)}"
