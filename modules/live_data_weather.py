from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from typing import Any

DEFAULT_LOCATION = "Bialystok"

def _http_json(url: str, timeout: int = 15) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HALbridge/1.0 live-data-weather"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))

def normalize_location(text: str | None) -> str:
    if not text:
        return DEFAULT_LOCATION

    t = text.strip().lower()
    if t.startswith("w "):
        t = t[2:].strip()

    mapping = {
        "białystok": "Bialystok",
        "białymstoku": "Bialystok",
        "bialystok": "Bialystok",
        "warszawa": "Warsaw",
        "warszawie": "Warsaw",
        "kraków": "Krakow",
        "krakowie": "Krakow",
        "krakow": "Krakow",
        "wrocław": "Wroclaw",
        "wrocławiu": "Wroclaw",
        "wroclaw": "Wroclaw",
        "gdańsk": "Gdansk",
        "gdańsku": "Gdansk",
        "gdansk": "Gdansk",
    }

    return mapping.get(t, t.title())

def extract_location(query: str, context: dict | None = None) -> str:
    context = context or {}

    if context.get("location"):
        return normalize_location(str(context["location"]))

    q = query.strip().lower()

    known_locations = [
        "białymstoku", "białystok", "bialystok",
        "warszawie", "warszawa",
        "krakowie", "kraków", "krakow",
        "wrocławiu", "wrocław", "wroclaw",
        "gdańsku", "gdańsk", "gdansk",
    ]

    for loc in known_locations:
        if f"w {loc}" in q or q.endswith(loc) or f" {loc} " in f" {q} ":
            return normalize_location(loc)

    return DEFAULT_LOCATION

def detect_timeframe(query: str, context: dict | None = None) -> str:
    context = context or {}
    if context.get("timeframe"):
        return str(context["timeframe"]).lower()
    q = query.lower()
    if "jutro" in q:
        return "jutro"
    if "dziś" in q or "dzis" in q or "dzisiaj" in q:
        return "dziś"
    return "teraz"

def get_weather(query: str, context: dict | None = None) -> dict[str, Any]:
    context = context or {}
    location = extract_location(query, context)
    timeframe = detect_timeframe(query, context)
    loc_encoded = urllib.parse.quote(location)
    url = f"https://wttr.in/{loc_encoded}?format=j1&lang=pl"

    try:
        data = _http_json(url)
        current = data["current_condition"][0]
        today = data["weather"][0]

        current_temp = current.get("temp_C")
        feels_like = current.get("FeelsLikeC")
        desc = ", ".join(x.get("value", "") for x in current.get("lang_pl", []) or current.get("weatherDesc", []))
        max_temp = today.get("maxtempC")
        min_temp = today.get("mintempC")

        if timeframe == "jutro" and len(data.get("weather", [])) > 1:
            day = data["weather"][1]
            max_temp = day.get("maxtempC")
            min_temp = day.get("mintempC")
            summary = (
                f"Pogoda jutro dla {location}: przewidywany zakres temperatur {min_temp} do {max_temp}°C."
            )
        else:
            summary = (
                f"Pogoda dla {location}: teraz {current_temp}°C, odczuwalna {feels_like}°C, "
                f"warunki: {desc}. Dziś zakres temperatur {min_temp} do {max_temp}°C."
            )

        return {
            "ok": True,
            "type": "weather",
            "location": location,
            "timeframe": timeframe,
            "summary": summary,
            "raw": data,
        }
    except Exception as e:
        return {
            "ok": False,
            "type": "weather",
            "location": location,
            "timeframe": timeframe,
            "error": f"{type(e).__name__}: {e}",
            "summary": f"Nie udało się pobrać pogody dla {location}.",
        }
