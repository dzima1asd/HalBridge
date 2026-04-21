from __future__ import annotations

from typing import Any

from modules.context_policy_v4 import choose_context_mode, looks_like_followup_text
from modules.voice_dispatch import decide_dispatch
from modules.voice_orchestrator import plan_voice_action, recent_youtube_context
from modules.voice_router import classify_voice_route


def decide_voice_intent_v4(
    *,
    text: str,
    wake_result: dict[str, Any] | None = None,
    has_session: bool = False,
) -> dict[str, Any]:
    raw = (text or "").strip()
    wake_result = wake_result or {}

    orchestrator_result = plan_voice_action(raw)
    orchestrator_mode = str(orchestrator_result.get("mode") or "").strip()
    classified_route_result = classify_voice_route(raw)
    classified_route = str(classified_route_result.get("route") or "unknown")
    classified_score = float(classified_route_result.get("score", 0.0) or 0.0)
    low = raw.lower().strip()

    forced_route = None
    forced_final_text = raw

    if orchestrator_mode == "device_command":
        forced_route = "device"
    elif orchestrator_mode == "youtube_command":
        forced_route = "youtube"
        orchestrator_query = str(orchestrator_result.get("query") or "").strip()
        if orchestrator_query:
            forced_final_text = orchestrator_query
    elif orchestrator_mode == "knowledge_question":
        forced_route = "conversation"
    elif orchestrator_mode == "propose_action":
        execute_text = str(orchestrator_result.get("execute_text") or raw).strip()
        reply_text = str(orchestrator_result.get("reply_text") or f"Potwierdź proszę: {execute_text}").strip()
        return {
            "ok": True,
            "route": str(orchestrator_result.get("route") or "device"),
            "action": "ask_confirm",
            "final_text": execute_text,
            "reply_text": reply_text,
            "confidence": float(orchestrator_result.get("confidence", 0.75) or 0.75),
            "reason": str(orchestrator_result.get("reason") or "affordance_proposal"),
            "context_mode": "light",
            "context_reason": "affordance_proposal",
            "route_result": {
                "ok": True,
                "text": execute_text,
                "route": str(orchestrator_result.get("route") or "device"),
                "score": float(orchestrator_result.get("confidence", 0.75) or 0.75),
                "scores": {str(orchestrator_result.get("route") or "device"): float(orchestrator_result.get("confidence", 0.75) or 0.75)},
                "reason": str(orchestrator_result.get("reason") or "affordance_proposal"),
                "matches": {"orchestrator_mode": orchestrator_mode},
            },
            "dispatch_result": {
                "ok": True,
                "action": "ask_confirm",
                "route": str(orchestrator_result.get("route") or "device"),
                "final_text": execute_text,
                "reason": str(orchestrator_result.get("reason") or "affordance_proposal"),
                "reply_text": reply_text,
                "confirmation_required": True,
                "handled": True,
                "pending_action": {
                    "route": str(orchestrator_result.get("route") or "device"),
                    "final_text": execute_text,
                    "reply_text": reply_text,
                },
            },
            "orchestrator_result": orchestrator_result,
        }
    elif orchestrator_mode == "unknown":
        followup_like_any = looks_like_followup_text(raw)
        followup_like_with_session = has_session and followup_like_any

        if followup_like_any and not has_session:
            return {
                "ok": True,
                "route": "unknown",
                "action": "ask_repeat",
                "final_text": raw,
                "reply_text": "Doprecyzuj proszę, do czego mam się odnieść.",
                "confidence": float(orchestrator_result.get("confidence", 0.0) or 0.0),
                "reason": "followup_without_session_guard",
                "context_mode": "stateless",
                "route_result": {
                    "ok": True,
                    "text": raw,
                    "route": "unknown",
                    "score": float(orchestrator_result.get("confidence", 0.0) or 0.0),
                    "scores": {"unknown": float(orchestrator_result.get("confidence", 0.0) or 0.0)},
                    "reason": "followup_without_session_guard",
                    "matches": {"orchestrator_mode": orchestrator_mode},
                },
                "dispatch_result": {
                    "ok": True,
                    "action": "ask_repeat",
                    "route": "unknown",
                    "final_text": raw,
                    "reason": "followup_without_session_guard",
                    "confirmation_required": False,
                    "handled": True,
                },
                "orchestrator_result": orchestrator_result,
            }

        recoverable_unknown = (
            (classified_route in {"conversation", "smart_query"} and classified_score >= 0.35)
            or followup_like_with_session
        )
        if not recoverable_unknown:
            ask_repeat_text = "Powtórz proszę"
            if recent_youtube_context():
                ask_repeat_text = "Powtórz tytuł"
            return {
                "ok": True,
                "route": "unknown",
                "action": "ask_repeat",
                "final_text": raw,
                "reply_text": ask_repeat_text,
                "confidence": float(orchestrator_result.get("confidence", 0.0) or 0.0),
                "reason": "orchestrator_unknown_guard",
                "context_mode": "stateless",
                "route_result": {
                    "ok": True,
                    "text": raw,
                    "route": "unknown",
                    "score": float(orchestrator_result.get("confidence", 0.0) or 0.0),
                    "scores": {"unknown": float(orchestrator_result.get("confidence", 0.0) or 0.0)},
                    "reason": "voice_orchestrator_unknown_guard",
                    "matches": {"orchestrator_mode": orchestrator_mode},
                },
                "dispatch_result": {
                    "ok": True,
                    "action": "ask_repeat",
                    "route": "unknown",
                    "final_text": raw,
                    "reason": "voice_orchestrator_unknown_guard",
                    "confirmation_required": False,
                    "handled": True,
                },
                "orchestrator_result": orchestrator_result,
            }

    if forced_route:
        route_result = {
            "ok": True,
            "text": raw,
            "route": forced_route,
            "score": float(orchestrator_result.get("confidence", 0.95) or 0.95),
            "scores": {forced_route: float(orchestrator_result.get("confidence", 0.95) or 0.95)},
            "reason": f"voice_orchestrator:{orchestrator_result.get('reason', orchestrator_mode)}",
            "matches": {"orchestrator_mode": orchestrator_mode},
        }
        dispatch_result = {
            "ok": True,
            "action": "reroute_to_agent" if forced_route == "conversation" else "execute",
            "route": forced_route,
            "final_text": forced_final_text,
            "reason": f"voice_orchestrator_{forced_route}",
            "confirmation_required": False,
            "handled": True,
        }
    else:
        route_result = classified_route_result
        dispatch_result = decide_dispatch(
            text=raw,
            route_result=route_result,
            wake_result=wake_result,
        )

    route = str(route_result.get("route") or "unknown")
    final_text = str(dispatch_result.get("final_text") or raw).strip()
    action = str(dispatch_result.get("action") or "reject")
    confidence = float(route_result.get("score", 0.0) or 0.0)

    ctx = choose_context_mode(
        route=route,
        text=final_text,
        has_session=has_session,
        force_session=False,
    )

    return {
        "ok": True,
        "route": route,
        "action": action,
        "final_text": final_text,
        "reply_text": "",
        "confidence": confidence,
        "reason": str(dispatch_result.get("reason") or route_result.get("reason") or "v4_decision"),
        "context_mode": str(ctx.get("mode") or "light"),
        "context_reason": str(ctx.get("reason") or "unknown"),
        "route_result": route_result,
        "dispatch_result": dispatch_result,
        "orchestrator_result": orchestrator_result,
    }
