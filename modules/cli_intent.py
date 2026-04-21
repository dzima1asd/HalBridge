from __future__ import annotations
# explicit CLI intent path using shared intent execution flow

from modules.intent_execution_flow import execute_intent_flow



def handle_intent_line(line: str) -> tuple[bool, str | None]:
    if not line.startswith("intent "):
        return False, None

    text = line[7:].strip()
    if not text:
        return True, "⚠️ Brak treści po komendzie intent."

    try:
        result = execute_intent_flow(text)

        if result.get("kind") == "ask":
            return True, result.get("message")

        if result.get("kind") == "plan":
            return True, result.get("message")

        if result.get("kind") == "error":
            if result.get("error") == "unsupported_plan_module":
                plan = (result.get("result") or {}).get("plan") or {}
                module = plan.get("module") or "unknown"
                action = plan.get("action") or "unknown"
                return True, f"⚠️ Rozpoznano intencję, ale moduł planu nie jest jeszcze obsługiwany: {module} ({action})"
            return True, f"[INTENT][ERR] {result.get('error')}"

        return True, str(result)

    except Exception as e:
        return True, f"[INTENT][ERR] {type(e).__name__}: {e}"
