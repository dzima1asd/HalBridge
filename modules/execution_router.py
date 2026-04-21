from __future__ import annotations

from typing import Any

from modules.agent_device_layer import device_command
from modules.agent_runtime import get_api
from modules.execution_classifier import resolve_route
from modules.execution_models import (
    ExecutionRequest,
    ExecutionResult,
    make_error_result,
    make_success_result,
)
from modules.intent_execution_adapter import execute_intent_as_execution_result
from modules.input_normalizer import normalize
import json
from pathlib import Path


def _safe_text(text: Any) -> str:
    return (str(text or "")).strip()


def execute_request(request: ExecutionRequest) -> ExecutionResult:
    raw_text = _safe_text(request.text)
    if not raw_text:
        return make_error_result(
            route="unknown",
            action="reject",
            reply_text="Brak treści do wykonania.",
            error="empty_text",
            telemetry={
                "source": request.source,
                "session_id": request.session_id,
            },
            handled=False,
        )

    normalized_text = normalize(raw_text)
    if not normalized_text:
        return make_error_result(
            route="unknown",
            action="reject",
            reply_text="Nie udało się znormalizować polecenia.",
            error="empty_normalized_text",
            telemetry={
                "source": request.source,
                "session_id": request.session_id,
                "raw_text": raw_text,
            },
            handled=False,
        )

    route = resolve_route(request, normalized_text)

    if route == "hardware":
        try:
            hw = device_command(normalized_text)
        except Exception as e:
            return make_error_result(
                route="hardware",
                action="error",
                reply_text="Błąd podczas wykonywania komendy sprzętowej.",
                error=str(e),
                telemetry={
                    "source": request.source,
                    "session_id": request.session_id,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                },
                handled=False,
            )

        if hw:
            return make_success_result(
                route="hardware",
                action="execute",
                reply_text=str(hw),
                data=hw,
                confidence=0.9,
                telemetry={
                    "source": request.source,
                    "session_id": request.session_id,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                },
            )

        return make_error_result(
            route="hardware",
            action="reject",
            reply_text="Nie udało się wykonać komendy sprzętowej.",
            error="hardware_not_executed",
            telemetry={
                "source": request.source,
                "session_id": request.session_id,
                "raw_text": raw_text,
                "normalized_text": normalized_text,
            },
            handled=False,
        )


    if route == "youtube":
        try:
            queue_path = Path("/home/hal/HALbridge/state/voice_command_queue.jsonl")
            queue_path.parent.mkdir(parents=True, exist_ok=True)
            cmd = normalized_text
            low = cmd.lower()
            if low.startswith("włącz youtube "):
                cmd = "yt " + cmd[len("włącz youtube "):].strip()
            elif low.startswith("wlacz youtube "):
                cmd = "yt " + cmd[len("wlacz youtube "):].strip()
            elif low.startswith("youtube "):
                cmd = "yt " + cmd[len("youtube "):].strip()
            row = {"command": cmd, "source": request.source, "session_id": request.session_id}
            with queue_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            return make_error_result(
                route="youtube",
                action="error",
                reply_text="Błąd podczas kolejkowania komendy YouTube.",
                error=str(e),
                telemetry={
                    "source": request.source,
                    "session_id": request.session_id,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                },
                handled=False,
            )

        return make_success_result(
            route="youtube",
            action="enqueue",
            reply_text=f"🎵 Dodano do kolejki YouTube: {cmd}",
            data=cmd,
            confidence=0.9,
            telemetry={
                "source": request.source,
                "session_id": request.session_id,
                "raw_text": raw_text,
                "normalized_text": normalized_text,
            },
        )

    if route == "conversation":
        short_tokens = normalized_text.strip().split()
        is_short_definition = (
            len(short_tokens) <= 8
            and normalized_text.lower().startswith(("co to", "kim jest", "czym jest"))
        )

        try:
            api = get_api(session_id=request.session_id or "execution_router")
            if is_short_definition:
                out = api.ask_ai_local_stateless(normalized_text, note="local_definition")
                return make_success_result(
                    route="conversation",
                    action="respond",
                    reply_text=str(out),
                    data=out,
                    confidence=0.95,
                    telemetry={
                        "source": request.source,
                        "session_id": request.session_id,
                        "raw_text": raw_text,
                        "normalized_text": normalized_text,
                        "fast_path": "local_definition_llm",
                    },
                )

            api = get_api(session_id=request.session_id or "execution_router")
            meta = request.metadata or {}
            context_mode = str(meta.get("context_mode") or "").strip().lower()

            if context_mode == "stateless":
                out = api.ask_ai_stateless(normalized_text, execute=False, note="cli_tools")
            elif context_mode == "light":
                out = api.ask_ai_light(normalized_text, execute=False, note="cli_tools")
            else:
                out = api.ask_ai(normalized_text, execute=False, note="cli_tools", context_mode="session")
        except Exception as e:
            return make_error_result(
                route="conversation",
                action="error",
                reply_text="Błąd podczas odpowiedzi agenta.",
                error=str(e),
                telemetry={
                    "source": request.source,
                    "session_id": request.session_id,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                },
                handled=False,
            )

        return make_success_result(
            route="conversation",
            action="respond",
            reply_text=str(out),
            data=out,
            confidence=0.7,
            telemetry={
                "source": request.source,
                "session_id": request.session_id,
                "raw_text": raw_text,
                "normalized_text": normalized_text,
            },
        )

    if route == "smart_query":
        try:
            api = get_api(session_id=request.session_id or "execution_router")
            out = api.run_web_research(normalized_text, intent={"queries": [normalized_text]})
        except Exception as e:
            return make_error_result(
                route="smart_query",
                action="error",
                reply_text="Błąd podczas web research dla smart_query.",
                error=str(e),
                telemetry={
                    "source": request.source,
                    "session_id": request.session_id,
                    "raw_text": raw_text,
                    "normalized_text": normalized_text,
                },
                handled=False,
            )

        return make_success_result(
            route="smart_query",
            action="respond",
            reply_text=str(out),
            data=out,
            confidence=0.7,
            telemetry={
                "source": request.source,
                "session_id": request.session_id,
                "raw_text": raw_text,
                "normalized_text": normalized_text,
            },
        )

    if route == "intent":
        return execute_intent_as_execution_result(
            normalized_text,
            source=request.source,
            session_id=request.session_id or "execution_router",
        )

    return make_error_result(
        route="unknown",
        action="reject",
        reply_text="Nie znalazłem odpowiedniej ścieżki wykonania.",
        error="unresolved_route",
        telemetry={
            "source": request.source,
            "session_id": request.session_id,
            "raw_text": raw_text,
            "normalized_text": normalized_text,
        },
        handled=False,
    )


def execute_text(
    text: str,
    *,
    source: str = "unknown",
    session_id: str = "default",
    user_id: str | None = None,
    actor: str | None = None,
    mode: str = "default",
    metadata: dict[str, Any] | None = None,
    raw_input: Any = None,
) -> ExecutionResult:
    request = ExecutionRequest.from_text(
        text,
        source=source,
        session_id=session_id,
        user_id=user_id,
        actor=actor,
        mode=mode,
        metadata=metadata,
        raw_input=raw_input,
    )
    return execute_request(request)
