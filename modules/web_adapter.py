from __future__ import annotations

from modules.tools import web_fetch


def fetch(url: str = "", query: str = "") -> dict:
    payload = {}

    url = (url or "").strip()
    query = (query or "").strip()

    if url:
        payload["url"] = url
    if query:
        payload["query"] = query

    if not payload:
        raise ValueError("Provide 'url' or 'query'")

    result = web_fetch.invoke(payload)

    return {
        "ok": True,
        "handled": True,
        "input": payload,
        "raw_result": result,
    }
