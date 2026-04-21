from __future__ import annotations

from typing import Any


def build_voice_response_from_kernel(
    *,
    build_response_fn,
    log_voice_event_fn,
    route: str,
    final_text: str,
    prep: dict[str, Any],
    route_result: dict[str, Any],
    wake_result: dict[str, Any],
    dispatch_result: dict[str, Any],
    assist_result: dict[str, Any],
    kernel_result: dict[str, Any],
) -> dict[str, Any]:
    handled = bool(kernel_result.get("handled", False))
    kernel_error = kernel_result.get("error")
    reply_text = (kernel_result.get("reply_text") or "").strip()

    if route == "device":
        dispatch_reply = str(dispatch_result.get("reply_text") or "").strip()
        if handled and not kernel_error:
            if dispatch_reply and not dispatch_reply.endswith("?"):
                reply_text = dispatch_reply
            else:
                reply_text = "Wykonano komendę urządzenia."
        else:
            reply_text = "Nie udało się wykonać komendy urządzenia."
    elif route == "youtube":
        if handled and not kernel_error:
            reply_text = "Wykonuję komendę YouTube."
        else:
            reply_text = "Nie udało się wykonać komendy YouTube."
    elif not reply_text:
        reply_text = "Brak odpowiedzi kernela wykonania."

    action_taken = str(dispatch_result.get("action") or kernel_result.get("action") or "execute")

    log_voice_event_fn(
        "daemon_result",
        source="voice_daemon",
        current_state="executing",
        transcript=final_text,
        route=route,
        action_taken=action_taken,
        reply_text=reply_text,
        error=None if (handled and not kernel_error) else str(kernel_error or "kernel_failed"),
        data={
            "kernel_route": kernel_result.get("route"),
            "kernel_action": kernel_result.get("action"),
            "kernel_handled": handled,
        },
    )

    return build_response_fn(
        handled=handled,
        route=route,
        action_taken=action_taken,
        reply_text=reply_text,
        needs_tts=True,
        confirmation_required=bool(kernel_result.get("requires_confirmation", False)),
        final_text=final_text,
        preprocess=prep,
        route_result=route_result,
        wake_result=wake_result,
        dispatch_result=dispatch_result,
        assist_result=assist_result,
        downstream=kernel_result,
        error=None if (handled and not kernel_error) else str(kernel_error or "kernel_failed"),
    )
