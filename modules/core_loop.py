# CORE LOOP — HALbridge
# deprecated transitional module kept temporarily for migration safety
# no active live callers in current CLI / voice / server paths

from modules.input_normalizer import normalize
from modules.intent_execution_flow import execute_intent_flow
# hardware routing moved out of core_loop into the shared execution/kernel path
from modules.cli_codegen import handle_codegen_line
from modules.agent_runtime import get_api

def run(user_input: str):
    print("[CORE] raw:", user_input)

    text = normalize(user_input)
    print("[CORE] normalized:", text)

    # 0. jawny code → codegen
    if text.startswith("code "):
        print("[CORE] explicit code → codegen")
        try:
            api = get_api(session_id="core_loop")
            handled, out = handle_codegen_line(text, api)
            if handled:
                return {
                    "ok": True,
                    "route": "codegen",
                    "status": "codegen",
                    "message": out,
                    "data": out,
                }
        except Exception as e:
            return {
                "ok": False,
                "route": "codegen",
                "status": "error",
                "data": str(e),
            }

    # 1. hardware path intentionally disabled here
    # hardware is handled by the shared execution/kernel path before core_loop
    result = execute_intent_flow(text)
    print("[CORE] intent flow result:", result)

    # 2. PLAN
    if result.get("kind") == "plan":
        exec_result = result.get("execution") or {}
        return {
            "ok": bool(result.get("ok")),
            "route": "plan",
            "status": "plan_executed" if result.get("ok") else "plan_error",
            "message": result.get("message"),
            "data": {
                "plan": result.get("plan"),
                "execution": exec_result,
                "result": result.get("result"),
            },
        }

    # 3. ASK
    if result.get("kind") == "ask":
        return {
            "ok": True,
            "route": "ask",
            "status": "ask",
            "message": result.get("message"),
            "data": result.get("result"),
        }

    # 4. UNKNOWN INTENT
    if result.get("kind") == "error" and result.get("error") == "unknown_intent":
        return {
            "ok": False,
            "route": "intent",
            "status": "unknown_intent",
            "data": result.get("result"),
        }

    # 5. inne błędy
    if result.get("kind") == "error":
        return {
            "ok": False,
            "route": "intent",
            "status": "error",
            "data": result.get("result"),
        }

    return {
        "ok": False,
        "route": "unknown",
        "status": "unknown",
        "data": result,
    }
