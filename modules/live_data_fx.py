from __future__ import annotations

import json
import re
import urllib.request
from typing import Any

NBP_CODE_MAP = {
    "dolar": "USD",
    "dolara": "USD",
    "usd": "USD",
    "euro": "EUR",
    "eur": "EUR",
    "frank": "CHF",
    "franka": "CHF",
    "chf": "CHF",
    "funt": "GBP",
    "funta": "GBP",
    "gbp": "GBP",
}

def _http_json(url: str, timeout: int = 12) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HALbridge/1.0 live-data-fx"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def detect_currency_code(query: str) -> str | None:
    q = query.lower()
    for k, v in NBP_CODE_MAP.items():
        if k in q:
            return v
    return None

def get_fx(query: str, context: dict | None = None) -> dict[str, Any]:
    context = context or {}
    code = detect_currency_code(query)
    if not code:
        return {
            "ok": False,
            "type": "fx",
            "error": "currency_not_detected",
            "summary": "Nie wykryto waluty w pytaniu.",
        }

    url = f"https://api.nbp.pl/api/exchangerates/rates/A/{code}/?format=json"
    try:
        data = _http_json(url)
        rate = data["rates"][0]["mid"]
        effective_date = data["rates"][0]["effectiveDate"]
        currency = data.get("currency", code)
        summary = f"Kurs {currency} ({code}) według NBP wynosi {rate} PLN na dzień {effective_date}."
        return {
            "ok": True,
            "type": "fx",
            "code": code,
            "rate": rate,
            "date": effective_date,
            "raw": data,
            "summary": summary,
        }
    except Exception as e:
        return {
            "ok": False,
            "type": "fx",
            "code": code,
            "error": f"{type(e).__name__}: {e}",
            "summary": f"Nie udało się pobrać kursu {code}.",
        }
