from __future__ import annotations

from typing import Any


def build_reject_response_v4(
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
) -> dict[str, Any]:
    reason = str(dispatch_result.get("reason") or "rejected")

    if reason == "wake_gate_block":
        reply = "Dla tej komendy wymagane jest wybudzenie słowem kluczowym."
    elif reason == "unsafe_candidate_rejected":
        reply = "Ta komenda wygląda na niebezpieczną, więc ją odrzucam."
    else:
        reply = "Nie mogę tego wykonać."

    log_voice_event_fn(
        "daemon_result",
        source="voice_daemon",
        current_state="dispatching",
        transcript=final_text,
        route=route,
        action_taken="reject",
        reply_text=reply,
        error=reason,
    )

    return build_response_fn(
        handled=bool(dispatch_result.get("handled", False)),
        route=route,
        action_taken="reject",
        reply_text=reply,
        needs_tts=True,
        confirmation_required=False,
        final_text=final_text,
        preprocess=prep,
        route_result=route_result,
        wake_result=wake_result,
        dispatch_result=dispatch_result,
        assist_result=assist_result,
    )


def build_ask_confirm_response_v4(
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
) -> dict[str, Any]:
    ask_reason = str(dispatch_result.get("reason") or "")
    ask_reply = str(dispatch_result.get("reply_text") or f"Potwierdź proszę: {final_text}")
    ask_needs_tts = ask_reason != "unknown_too_short"

    log_voice_event_fn(
        "daemon_result",
        source="voice_daemon",
        current_state="dispatching",
        transcript=final_text,
        route=route,
        action_taken="ask_confirm",
        reply_text=ask_reply,
        data={
            "confirmation_required": True,
            "needs_tts": ask_needs_tts,
            "reason": ask_reason,
        },
    )

    return build_response_fn(
        handled=True,
        route=route,
        action_taken="ask_confirm",
        reply_text=ask_reply,
        needs_tts=ask_needs_tts,
        confirmation_required=True,
        final_text=final_text,
        preprocess=prep,
        route_result=route_result,
        wake_result=wake_result,
        dispatch_result=dispatch_result,
        assist_result=assist_result,
    )
