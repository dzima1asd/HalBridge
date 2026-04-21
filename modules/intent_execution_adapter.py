from __future__ import annotations

from modules.execution_models import make_error_result, make_success_result
from modules.intent_execution_flow import execute_intent_flow


def execute_intent_as_execution_result(text: str, *, source: str, session_id: str):
    result = execute_intent_flow(text)

    if result.get("kind") == "ask":
        return make_success_result(
            route="intent",
            action="ask",
            reply_text=str(result.get("message") or ""),
            data=result.get("result"),
            confidence=0.7,
            telemetry={
                "source": source,
                "session_id": session_id,
                "intent_kind": "ask",
            },
        )

    if result.get("kind") == "plan":
        ok = bool(result.get("ok"))
        if ok:
            return make_success_result(
                route="intent",
                action="plan_execute",
                reply_text=str(result.get("message") or ""),
                data={
                    "plan": result.get("plan"),
                    "execution": result.get("execution"),
                    "result": result.get("result"),
                },
                confidence=0.8,
                telemetry={
                    "source": source,
                    "session_id": session_id,
                    "intent_kind": "plan",
                },
            )
        return make_error_result(
            route="intent",
            action="plan_execute",
            reply_text=str(result.get("message") or ""),
            error="plan_execution_failed",
            data={
                "plan": result.get("plan"),
                "execution": result.get("execution"),
                "result": result.get("result"),
            },
            telemetry={
                "source": source,
                "session_id": session_id,
                "intent_kind": "plan",
            },
            handled=False,
        )

    if result.get("kind") == "error":
        return make_error_result(
            route="intent",
            action="error",
            reply_text="",
            error=str(result.get("error") or "intent_error"),
            data=result.get("result"),
            telemetry={
                "source": source,
                "session_id": session_id,
                "intent_kind": "error",
            },
            handled=False,
        )

    return make_error_result(
        route="intent",
        action="reject",
        reply_text="",
        error="intent_unknown_result",
        data=result,
        telemetry={
            "source": source,
            "session_id": session_id,
            "intent_kind": "unknown",
        },
        handled=False,
    )
