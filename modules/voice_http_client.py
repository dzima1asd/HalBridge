from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any


BASE_URL = "http://127.0.0.1:5001"
API_TOKEN = os.environ.get("HALBRIDGE_API_TOKEN", "change_me")


def _post_json(path: str, payload: dict[str, Any], timeout: float = 10.0) -> dict[str, Any]:
    url = BASE_URL + path
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "X-API-Token": API_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return {
                "ok": True,
                "status": resp.status,
                "body": body,
                "url": url,
                "error": None,
            }
    except TimeoutError as e:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "url": url,
            "error": f"TimeoutError: {e}",
        }
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": e.code,
            "body": body,
            "url": url,
            "error": f"HTTPError: {e.code} {e.reason}",
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "body": None,
            "url": url,
            "error": f"{type(e).__name__}: {e}",
        }


def post_agent_ask(prompt: str, source: str = "voice", original_text: str = "") -> dict[str, Any]:
    payload = {
        "prompt": prompt,
        "source": source,
        "original_text": original_text,
    }
    return _post_json("/agent/ask", payload, timeout=45.0)


def post_hardware_run(text: str, source: str = "voice", original_text: str = "") -> dict[str, Any]:
    payload = {
        "command": text,
        "source": source,
        "original_text": original_text,
    }
    return _post_json("/hardware/run", payload)


if __name__ == "__main__":
    pass
