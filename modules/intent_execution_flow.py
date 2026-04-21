from __future__ import annotations

from modules.intent_pipeline import intent_pipeline
from modules.plan_executor import execute_plan
from modules.plan_presenter import render_plan_execution


def execute_intent_flow(text: str) -> dict:
    result = intent_pipeline(text)

    if "ask" in result:
        return {
            "kind": "ask",
            "ok": True,
            "message": result.get("ask"),
            "result": result,
        }

    if "plan" in result:
        exec_result = execute_plan(result["plan"])
        return {
            "kind": "plan",
            "ok": bool(exec_result.get("ok")),
            "message": render_plan_execution(exec_result),
            "plan": result["plan"],
            "execution": exec_result,
            "result": result,
        }

    if "error" in result:
        return {
            "kind": "error",
            "ok": False,
            "error": result.get("error"),
            "result": result,
        }

    return {
        "kind": "unknown",
        "ok": False,
        "result": result,
    }
