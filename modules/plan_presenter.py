from __future__ import annotations

def render_plan_execution(exec_result: dict) -> str:
    if not isinstance(exec_result, dict):
        return f"PLAN ERROR: invalid execution result: {exec_result!r}"

    if exec_result.get("ok"):
        module = exec_result.get("module")
        action = exec_result.get("action")

        if module == "system_exec":
            stdout = (exec_result.get("stdout") or "").strip()
            stderr = (exec_result.get("stderr") or "").strip()

            if stdout:
                return stdout
            if stderr:
                return stderr
            return "✅ Komenda wykonana."

        if module == "hardware_bridge":
            result = exec_result.get("result")
            if isinstance(result, str) and result.strip():
                return result.strip()
            return f"✅ Wykonano akcję: {action}"

        result = exec_result.get("result")
        if isinstance(result, str) and result.strip():
            return result.strip()

        return f"✅ OK: {exec_result}"

    err = exec_result.get("error", "unknown_error")
    details = exec_result.get("details")
    module = exec_result.get("module")
    action = exec_result.get("action")

    msg = f"PLAN ERROR: {err}"
    if module:
        msg += f" | module={module}"
    if action:
        msg += f" | action={action}"
    if details:
        msg += f" | {details}"
    return msg
