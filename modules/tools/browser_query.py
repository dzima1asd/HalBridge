import json
from .browser_mode import perform_browser_query


def browser_query(url: str, html: str) -> str:
    """
    Cienka otoczka na perform_browser_query:
    - bierze URL + HTML
    - odpala istniejący parser (tytuł, linki, streszczenie)
    - zwraca wynik jako JSON string (pod toola GPT)
    """
    data = perform_browser_query(url, html)
    return json.dumps(data, ensure_ascii=False)

def invoke(payload: dict):
    url = payload.get("url")
    html = payload.get("html")

    if not url or not html:
        return {"ok": False, "error": "missing url or html"}

    return {
        "ok": True,
        "result": perform_browser_query(url, html)
    }
