from __future__ import annotations

from typing import Any


DEFAULT_THRESHOLDS = {
    "device_execute_min": 0.65,
    "system_execute_min": 0.80,
    "youtube_execute_min": 0.70,
    "smart_query_execute_min": 0.40,
    "conversation_reroute_min": 0.35,
    "unsafe_reject_min": 0.70,
}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def decide_dispatch(
    *,
    text: str,
    route_result: dict[str, Any] | None = None,
    wake_result: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_result = route_result or {}
    wake_result = wake_result or {}
    cfg = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        cfg.update(thresholds)

    route = str(route_result.get("route") or "unknown")
    score = _safe_float(route_result.get("score", 0.0), 0.0)
    wake_required = bool(wake_result.get("wake_required", False))
    wake_detected = bool(wake_result.get("wake_detected", False))
    wake_allowed = bool(wake_result.get("allowed", not wake_required))

    stripped_text = (wake_result.get("stripped_text") or text or "").strip()
    tokens = stripped_text.split()
    reason = "default_unknown"

    if not stripped_text:
        return {
            "ok": False,
            "action": "reject",
            "route": route,
            "final_text": "",
            "reason": "empty_text",
            "confirmation_required": False,
            "handled": False,
        }

    if wake_required and not wake_allowed:
        return {
            "ok": False,
            "action": "reject",
            "route": route,
            "final_text": stripped_text,
            "reason": "wake_gate_block",
            "confirmation_required": False,
            "handled": False,
        }

    if route == "unsafe_candidate":
        if score >= _safe_float(cfg["unsafe_reject_min"], 0.70):
            return {
                "ok": True,
                "action": "reject",
                "route": route,
                "final_text": stripped_text,
                "reason": "unsafe_candidate_rejected",
                "confirmation_required": False,
                "handled": True,
            }
        return {
            "ok": True,
            "action": "ask_confirm",
            "route": route,
            "final_text": stripped_text,
            "reason": "unsafe_candidate_low_confidence",
            "confirmation_required": True,
            "handled": True,
        }

    if route == "device":
        if score >= _safe_float(cfg["device_execute_min"], 0.65):
            return {
                "ok": True,
                "action": "execute",
                "route": route,
                "final_text": stripped_text,
                "reason": "device_execute",
                "confirmation_required": False,
                "handled": True,
            }
        return {
            "ok": True,
            "action": "ask_confirm",
            "route": route,
            "final_text": stripped_text,
            "reason": "device_low_confidence",
            "confirmation_required": True,
            "handled": True,
        }

    if route == "system":
        if score >= _safe_float(cfg["system_execute_min"], 0.80):
            return {
                "ok": True,
                "action": "execute",
                "route": route,
                "final_text": stripped_text,
                "reason": "system_execute",
                "confirmation_required": False,
                "handled": True,
            }
        return {
            "ok": True,
            "action": "ask_confirm",
            "route": route,
            "final_text": stripped_text,
            "reason": "system_needs_confirmation",
            "confirmation_required": True,
            "handled": True,
        }

    if route == "youtube":
        if score >= _safe_float(cfg["youtube_execute_min"], 0.70):
            return {
                "ok": True,
                "action": "execute",
                "route": route,
                "final_text": stripped_text,
                "reason": "youtube_execute",
                "confirmation_required": False,
                "handled": True,
            }
        return {
            "ok": True,
            "action": "ask_confirm",
            "route": route,
            "final_text": stripped_text,
            "reason": "youtube_low_confidence",
            "confirmation_required": True,
            "handled": True,
        }

    if route == "smart_query":
        if score >= _safe_float(cfg["smart_query_execute_min"], 0.55):
            return {
                "ok": True,
                "action": "reroute_to_agent",
                "route": route,
                "final_text": stripped_text,
                "reason": "smart_query_agent",
                "confirmation_required": False,
                "handled": True,
            }
        return {
            "ok": True,
            "action": "ask_confirm",
            "route": route,
            "final_text": stripped_text,
            "reason": "smart_query_low_confidence",
            "confirmation_required": True,
            "handled": True,
        }

    if route == "conversation":
        if score >= _safe_float(cfg["conversation_reroute_min"], 0.35):
            return {
                "ok": True,
                "action": "reroute_to_agent",
                "route": route,
                "final_text": stripped_text,
                "reason": "conversation_agent",
                "confirmation_required": False,
                "handled": True,
            }
        return {
            "ok": True,
            "action": "ask_confirm",
            "route": route,
            "final_text": stripped_text,
            "reason": "conversation_low_confidence",
            "confirmation_required": True,
            "handled": True,
        }

    if route == "unknown":
        if len(tokens) <= 1:
            return {
                "ok": True,
                "action": "ask_confirm",
                "route": route,
                "final_text": stripped_text,
                "reason": "unknown_too_short",
                "confirmation_required": True,
                "handled": True,
                "wake_detected": wake_detected,
            }

    return {
        "ok": True,
        "action": "reroute_to_agent",
        "route": route,
        "final_text": stripped_text,
        "reason": reason,
        "confirmation_required": False,
        "handled": True,
        "wake_detected": wake_detected,
    }


def dispatch_voice_text(
    text: str,
    route_result: dict[str, Any] | None = None,
    wake_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return decide_dispatch(
        text=text,
        route_result=route_result,
        wake_result=wake_result,
    )


if __name__ == "__main__":
    raise SystemExit("voice_dispatch.py is a module, not a standalone runner")
