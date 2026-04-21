from __future__ import annotations

from typing import Any

from modules.live_data_fx import get_fx
from modules.live_data_weather import get_weather

def detect_topic_from_query(query: str) -> str | None:
    q = query.lower()
    if any(x in q for x in ["pogoda", "temperatura"]):
        return "weather"
    if any(x in q for x in ["kurs", "dolar", "euro", "frank", "funt", "usd", "eur", "chf", "gbp"]):
        return "fx"
    if "imieniny" in q:
        return "calendar"
    return None

def handle_live_data(query: str, decision: Any = None, context: dict | None = None) -> dict[str, Any]:
    context = context or {}

    topic = None
    location = None
    timeframe = None

    if decision is not None:
        topic = getattr(decision, "topic", None)
        location = getattr(decision, "location", None)
        timeframe = getattr(decision, "timeframe", None)

    if not topic:
        topic = detect_topic_from_query(query)

    local_ctx = dict(context)
    if location and "location" not in local_ctx:
        local_ctx["location"] = location
    if timeframe and "timeframe" not in local_ctx:
        local_ctx["timeframe"] = timeframe

    if topic == "weather":
        return get_weather(query, local_ctx)

    if topic == "fx":
        return get_fx(query, local_ctx)

    if topic == "calendar":
        return {
            "ok": False,
            "type": "calendar",
            "error": "not_implemented_yet",
            "summary": "Obsługa imienin jest jeszcze niezaimplementowana w live_data.",
        }

    return {
        "ok": False,
        "type": "live_data",
        "error": "unknown_live_data_topic",
        "summary": "Nie udało się rozpoznać typu danych bieżących.",
    }
