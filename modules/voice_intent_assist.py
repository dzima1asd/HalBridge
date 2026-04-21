from __future__ import annotations

from typing import Any


DEFAULT_ASSIST_CONFIG = {
    "enabled": True,
    "route_confidence_min": 0.60,
    "force_for_unknown": True,
    "force_for_confirmation": False,
    "natural_phrase_token_threshold": 6,
}


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def should_use_intent_assist(
    *,
    text: str,
    route_result: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    route_result = route_result or {}
    dispatch_result = dispatch_result or {}
    cfg = dict(DEFAULT_ASSIST_CONFIG)
    if config:
        cfg.update(config)

    enabled = bool(cfg.get("enabled", True))
    raw = (text or "").strip()
    tokens = raw.split()
    route = str(route_result.get("route") or "unknown")
    score = _safe_float(route_result.get("score", 0.0), 0.0)
    dispatch_action = str(dispatch_result.get("action") or "")
    confirmation_required = bool(dispatch_result.get("confirmation_required", False))

    if not enabled:
        return {
            "ok": True,
            "use_assist": False,
            "reason": "assist_disabled",
            "route": route,
            "score": score,
        }

    if not raw:
        return {
            "ok": True,
            "use_assist": False,
            "reason": "empty_text",
            "route": route,
            "score": score,
        }

    if route == "unknown" and bool(cfg.get("force_for_unknown", True)):
        return {
            "ok": True,
            "use_assist": True,
            "reason": "unknown_route",
            "route": route,
            "score": score,
        }

    if score < _safe_float(cfg.get("route_confidence_min", 0.60), 0.60):
        return {
            "ok": True,
            "use_assist": True,
            "reason": "low_route_confidence",
            "route": route,
            "score": score,
        }

    if dispatch_action in {"reroute_to_agent"} and route in {"conversation", "smart_query"}:
        return {
            "ok": True,
            "use_assist": True,
            "reason": "needs_agent_reroute",
            "route": route,
            "score": score,
        }

    if confirmation_required and bool(cfg.get("force_for_confirmation", False)):
        return {
            "ok": True,
            "use_assist": True,
            "reason": "confirmation_required",
            "route": route,
            "score": score,
        }

    if len(tokens) >= int(cfg.get("natural_phrase_token_threshold", 6)) and route in {"conversation", "smart_query"}:
        return {
            "ok": True,
            "use_assist": True,
            "reason": "complex_natural_phrase",
            "route": route,
            "score": score,
        }

    return {
        "ok": True,
        "use_assist": False,
        "reason": "local_rules_sufficient",
        "route": route,
        "score": score,
    }


def maybe_use_intent_assist(
    text: str,
    route_result: dict[str, Any] | None = None,
    dispatch_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return should_use_intent_assist(
        text=text,
        route_result=route_result,
        dispatch_result=dispatch_result,
    )


if __name__ == "__main__":
    raise SystemExit("voice_intent_assist.py is a module, not a standalone runner")
