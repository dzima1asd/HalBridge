from __future__ import annotations

from typing import Any

from modules.execution_metadata_factory import build_voice_execution_metadata
from modules.execution_request_factory import build_voice_execution_request
from modules.execution_router import execute_request


def voice_kernel_route_hint(route: str) -> str:
    if route == "device":
        return "device"
    if route == "youtube":
        return "youtube"
    if route == "smart_query":
        return "smart_query"
    return "conversation"


def execute_voice_via_kernel(
    *,
    original_text: str,
    final_text: str,
    route: str,
    context_mode: str | None = None,
    route_result: dict[str, Any] | None = None,
    wake_result: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request = build_voice_execution_request(
        text=final_text,
        session_id="voice_daemon",
        actor="voice_execute",
        metadata=build_voice_execution_metadata(
            route_hint=voice_kernel_route_hint(route),
            voice_route=route,
            route_result=route_result,
            wake_result=wake_result,
            dispatch_result=dispatch_result,
            original_text=original_text,
            extra={
                "context_mode": context_mode,
            },
        ),
        raw_input={
            "original_text": original_text,
            "final_text": final_text,
        },
    )
    return execute_request(request).to_dict()


def voice_reply_from_kernel(route: str, kernel_result: dict[str, Any]) -> str:
    handled = bool(kernel_result.get("handled", False))
    kernel_error = kernel_result.get("error")
    kernel_reply = (kernel_result.get("reply_text") or "").strip()

    if route == "device":
        if handled and not kernel_error:
            return "Wykonano komendę urządzenia."
        return "Nie udało się wykonać komendy urządzenia."

    return kernel_reply or "Brak odpowiedzi kernela wykonania."
