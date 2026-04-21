from __future__ import annotations

from typing import Any

from modules.execution_models import ExecutionRequest


CONVERSATION_ROUTES = {
    "conversation",
    "system",
    "ask",
}

SMART_QUERY_ROUTES = {
    "smart_query",
}

YOUTUBE_ROUTES = {
    "youtube",
}

INTENT_ROUTES = {
    "intent",
    "plan",
    "codegen",
}

HARDWARE_ROUTES = {
    "device",
    "hardware",
}


def _extract_route_hint(request: ExecutionRequest) -> str:
    meta = request.metadata or {}
    hint = meta.get("route_hint")
    if hint:
        return str(hint).strip().lower()

    route_result = meta.get("route_result")
    if isinstance(route_result, dict):
        route = route_result.get("route")
        if route:
            return str(route).strip().lower()

    return ""


def resolve_route(request: ExecutionRequest, normalized_text: str) -> str:
    hint = _extract_route_hint(request)

    if hint in HARDWARE_ROUTES:
        return "hardware"

    if hint in INTENT_ROUTES:
        return "intent"

    if hint in YOUTUBE_ROUTES:
        return "youtube"

    if hint in SMART_QUERY_ROUTES:
        return "smart_query"

    if hint in CONVERSATION_ROUTES:
        return "conversation"

    if normalized_text:
        return "conversation"

    return "unknown"
