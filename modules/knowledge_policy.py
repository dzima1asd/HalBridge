from __future__ import annotations

FACTUAL_ROUTES = {"live_data", "current_facts", "news_research"}

def is_factual_route(route: str | None) -> bool:
    return (route or "").strip() in FACTUAL_ROUTES

def no_data_message(route: str | None) -> str:
    route = (route or "").strip()
    if route == "current_facts":
        return "Brak pewnych danych z aktualnych źródeł."
    if route == "live_data":
        return "Brak danych bieżących."
    if route == "news_research":
        return "Brak danych."
    return "Brak danych."
