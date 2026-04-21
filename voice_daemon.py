#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from typing import Any

from modules.voice_logger import log_voice_event
from modules.voice_kernel_bridge import execute_voice_via_kernel
from modules.voice_intent_pipeline_v4 import decide_voice_intent_v4
from modules.voice_response_adapter import build_voice_response_from_kernel
from modules.voice_response_policy_v4 import (
    build_ask_confirm_response_v4,
    build_reject_response_v4,
)
from modules.voice_preprocess import preprocess_voice_text
from modules.voice_router import classify_voice_route
from modules.voice_state import load_voice_state
from modules.voice_runtime_state import load_runtime_status
from modules.voice_session import is_session_active
from modules.voice_wake import analyze_wake
from modules.voice_pending_action import (
    clear_pending_action,
    is_affirmative,
    is_negative,
    load_pending_action,
    save_pending_action,
)
from modules.voice_preference_reasoner import reason_about_preference
from modules.voice_preferences import get_voice_preference, set_voice_preference


def build_response(
    *,
    handled: bool,
    route: str,
    action_taken: str,
    reply_text: str,
    needs_tts: bool,
    confirmation_required: bool,
    final_text: str,
    preprocess: dict[str, Any] | None = None,
    route_result: dict[str, Any] | None = None,
    wake_result: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    assist_result: dict[str, Any] | None = None,
    downstream: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    wake_payload = dict(wake_result or {})
    wake_payload.setdefault("wake_detected", False)
    wake_payload.setdefault("wake_word", None)
    wake_payload.setdefault("stripped_text", final_text or "")
    wake_payload.setdefault("session_active", False)

    return {
        "handled": handled,
        "route": route,
        "action_taken": action_taken,
        "needs_tts": needs_tts,
        "reply_text": reply_text,
        "confirmation_required": confirmation_required,
        "final_text": final_text,
        "preprocess": preprocess or {},
        "route_result": route_result or {},
        "wake_result": wake_payload,
        "dispatch_result": dispatch_result or {},
        "assist_result": assist_result or {},
        "downstream": downstream or {},
        "error": error,
    }


def resolve_wake_requirements(route: str, state: dict[str, Any]) -> tuple[bool, bool, dict[str, Any]]:
    runtime_status = load_runtime_status()
    session = runtime_status.get("session") or {}
    session_active = is_session_active(session)

    require_wake_for_device = bool(state.get("require_wake_for_device", True))
    require_wake_for_system = bool(state.get("require_wake_for_system", True))

    if session_active and route in {"device", "system"}:
        require_wake_for_device = False
        require_wake_for_system = False

    return require_wake_for_device, require_wake_for_system, {
        "session_active": session_active,
        "session": session,
    }


def process_voice_text(text: str) -> dict[str, Any]:
    state = load_voice_state()

    prep = preprocess_voice_text(text)
    if not prep.get("ok"):
        log_voice_event(
            "error",
            source="voice_daemon",
            current_state="preprocess",
            error=prep.get("reason"),
            data={"raw_text": text},
        )
        return build_response(
            handled=False,
            route="unknown",
            action_taken="reject",
            reply_text="Nie zrozumiałem wypowiedzi.",
            needs_tts=True,
            confirmation_required=False,
            final_text="",
            preprocess=prep,
            error=prep.get("reason"),
        )

    normalized_text = prep["text"]

    pending_action = load_pending_action()
    if pending_action:
        pref_decision = reason_about_preference(normalized_text, pending_action)

        if pref_decision.get("save_preference"):
            pref_name = pref_decision.get("preference_name")
            pref_value = pref_decision.get("preference_value")
            if pref_name is not None:
                set_voice_preference(str(pref_name), pref_value)

        if pref_decision.get("confirm_now") or is_affirmative(normalized_text):
            clear_pending_action()
            pending_route = str(pending_action.get("route") or "device")
            pending_text = str(pending_action.get("final_text") or "").strip()

            route_result = {
                "ok": True,
                "text": pending_text,
                "route": pending_route,
                "score": 1.0,
                "reason": "pending_action_confirmed",
            }
            wake_result = {
                "wake_detected": False,
                "wake_word": None,
                "stripped_text": normalized_text,
                "session_active": True,
            }
            dispatch_result = {
                "ok": True,
                "action": "execute",
                "route": pending_route,
                "final_text": pending_text,
                "reason": "pending_action_confirmed",
                "confirmation_required": False,
                "handled": True,
            }

            downstream = execute_voice_via_kernel(
                original_text=text,
                final_text=pending_text,
                route=pending_route,
                context_mode="stateless",
                route_result=route_result,
                wake_result=wake_result,
                dispatch_result=dispatch_result,
            )
            return build_voice_response_from_kernel(
                build_response_fn=build_response,
                log_voice_event_fn=log_voice_event,
                route=pending_route,
                final_text=pending_text,
                prep=prep,
                route_result=route_result,
                wake_result=wake_result,
                dispatch_result=dispatch_result,
                assist_result={
                    "ok": True,
                    "use_assist": False,
                    "reason": "pending_action_confirmed",
                    "route": pending_route,
                    "score": 1.0,
                },
                kernel_result=downstream,
            )

        if is_negative(normalized_text):
            clear_pending_action()
            return build_response(
                handled=True,
                route="conversation",
                action_taken="reject",
                reply_text="Dobra, nie wykonuję tej akcji.",
                needs_tts=True,
                confirmation_required=False,
                final_text=normalized_text,
                preprocess=prep,
                route_result={"ok": True, "route": "conversation", "text": normalized_text, "score": 1.0},
                wake_result={"wake_detected": False, "wake_word": None, "stripped_text": normalized_text, "session_active": True},
                dispatch_result={"ok": True, "action": "reject", "route": "conversation", "reason": "pending_action_cancelled", "handled": True},
                assist_result={"ok": True, "use_assist": False, "reason": "pending_action_cancelled", "route": "conversation", "score": 1.0},
                downstream=None,
                error=None,
            )

    initial_route_result = classify_voice_route(normalized_text)
    initial_route = initial_route_result.get("route", "unknown")

    log_voice_event(
        "route_selected",
        source="voice_daemon",
        current_state="routing",
        transcript=normalized_text,
        route=initial_route,
        data={"score": initial_route_result.get("score"), "reason": initial_route_result.get("reason")},
    )

    require_wake_for_device, require_wake_for_system, wake_context = resolve_wake_requirements(initial_route, state)

    wake_result = analyze_wake(
        normalized_text,
        active_wake_words=state.get("active_wake_words"),
        route_class=initial_route,
        require_wake_for_device=require_wake_for_device,
        require_wake_for_system=require_wake_for_system,
    )
    wake_result["session_active"] = wake_context.get("session_active", False)

    v4_result = decide_voice_intent_v4(
        text=(wake_result.get("stripped_text") or normalized_text).strip(),
        wake_result=wake_result,
        has_session=bool(wake_context.get("session_active", False)),
    )

    route_result = v4_result.get("route_result") or initial_route_result
    dispatch_result = v4_result.get("dispatch_result") or {}
    orchestrator_result = v4_result.get("orchestrator_result") or {}
    route = v4_result.get("route") or route_result.get("route", "unknown")

    if route == "youtube" and get_voice_preference("media_auto_execute", False):
        if dispatch_result.get("action") == "ask_confirm":
            dispatch_result["action"] = "execute"
            dispatch_result["confirmation_required"] = False
        if v4_result.get("action") == "ask_confirm":
            v4_result["action"] = "execute"

    if route == "device" and get_voice_preference("device_proposal_auto_execute", False):
        if str(dispatch_result.get("reason") or "").strip() in (
            "situation_darkness",
            "device_state_light_on",
            "device_state_light_off",
        ):
            if dispatch_result.get("action") == "ask_confirm":
                dispatch_result["action"] = "execute"
                dispatch_result["confirmation_required"] = False

                ft = str(dispatch_result.get("final_text") or "").strip()
                if ft.startswith("włącz "):
                    dispatch_result["reply_text"] = f"Włączam {ft[len('włącz '):].strip()}."
                elif ft.startswith("wyłącz "):
                    dispatch_result["reply_text"] = f"Wyłączam {ft[len('wyłącz '):].strip()}."
                else:
                    dispatch_result["reply_text"] = "Wykonuję komendę urządzenia."

            if v4_result.get("action") == "ask_confirm":
                v4_result["action"] = "execute"

    final_text = (v4_result.get("final_text") or dispatch_result.get("final_text") or wake_result.get("stripped_text") or normalized_text).strip()

    if v4_result.get("action") == "ask_repeat":
        ask_repeat_text = (v4_result.get("reply_text") or "Powtórz proszę").strip()
        return {
            "handled": True,
            "route": "unknown",
            "action_taken": "ask_repeat",
            "needs_tts": True,
            "reply_text": ask_repeat_text,
            "confirmation_required": False,
            "final_text": final_text,
            "preprocess": prep,
            "route_result": route_result,
            "orchestrator_result": orchestrator_result,
            "wake_result": wake_result,
            "dispatch_result": dispatch_result,
            "assist_result": {
                "ok": True,
                "use_assist": False,
                "reason": "v4_ask_repeat",
                "route": "unknown",
                "score": float(v4_result.get("confidence", 0.0) or 0.0),
            },
            "downstream": None,
            "error": None,
        }
    log_voice_event(
        "dispatch_selected",
        source="voice_daemon",
        current_state="dispatching",
        transcript=wake_result.get("stripped_text") or normalized_text,
        route=route,
        action_taken=dispatch_result.get("action"),
        data={
            "reason": dispatch_result.get("reason"),
            "confirmation_required": dispatch_result.get("confirmation_required"),
            "context_mode": v4_result.get("context_mode"),
            "context_reason": v4_result.get("context_reason"),
        },
    )

    assist_result = {
        "ok": True,
        "use_assist": False,
        "reason": "v4_pipeline_primary",
        "route": route,
        "score": float(v4_result.get("confidence", 0.0) or 0.0),
        "context_mode": v4_result.get("context_mode"),
        "context_reason": v4_result.get("context_reason"),
    }

    final_text = (dispatch_result.get("final_text") or "").strip()

    if dispatch_result.get("action") == "reject":
        return build_reject_response_v4(
            build_response_fn=build_response,
            log_voice_event_fn=log_voice_event,
            route=route,
            final_text=final_text,
            prep=prep,
            route_result=route_result,
            wake_result=wake_result,
            dispatch_result=dispatch_result,
            assist_result=assist_result,
        )

    if dispatch_result.get("action") == "ask_confirm":
        pending = dispatch_result.get("pending_action")
        if isinstance(pending, dict):
            save_pending_action(pending)
        return build_ask_confirm_response_v4(
            build_response_fn=build_response,
            log_voice_event_fn=log_voice_event,
            route=route,
            final_text=final_text,
            prep=prep,
            route_result=route_result,
            wake_result=wake_result,
            dispatch_result=dispatch_result,
            assist_result=assist_result,
        )

    if dispatch_result.get("action") in {"execute", "reroute_to_agent"}:
        clear_pending_action()
        downstream = execute_voice_via_kernel(
            original_text=text,
            final_text=final_text,
            route=route,
            context_mode=v4_result.get("context_mode"),
            route_result=route_result,
            wake_result=wake_result,
            dispatch_result=dispatch_result,
        )
        return build_voice_response_from_kernel(
            build_response_fn=build_response,
            log_voice_event_fn=log_voice_event,
            route=route,
            final_text=final_text,
            prep=prep,
            route_result=route_result,
            wake_result=wake_result,
            dispatch_result=dispatch_result,
            assist_result=assist_result,
            kernel_result=downstream,
        )

    return build_response(
        handled=False,
        route=route,
        action_taken="reject",
        reply_text="Nie udało się podjąć decyzji.",
        needs_tts=True,
        confirmation_required=False,
        final_text=final_text,
        preprocess=prep,
        route_result=route_result,
        wake_result=wake_result,
        dispatch_result=dispatch_result,
        assist_result=assist_result,
        error="no_dispatch_path",
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(json.dumps({
            "handled": False,
            "route": "unknown",
            "action_taken": "reject",
            "needs_tts": True,
            "reply_text": "Brak tekstu do przetworzenia.",
            "confirmation_required": False,
            "final_text": "",
            "error": "missing_text",
        }, ensure_ascii=False))
        return 1

    text = " ".join(argv[1:]).strip()
    result = process_voice_text(text)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("handled") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
