from __future__ import annotations

from modules.agent_device_layer import device_command


def execute_plan(plan: dict) -> dict:
    if not isinstance(plan, dict):
        return {"ok": False, "error": "invalid_plan"}

    module = plan.get("module")
    action = plan.get("action")
    slots = plan.get("slots", {}) or {}

    if module == "hardware_bridge":
        device = slots.get("device")

        if action == "iot.toggle":
            desired_state = slots.get("desired_state")
            if not device or desired_state not in {"on", "off"}:
                return {
                    "ok": False,
                    "error": "missing_device_or_desired_state",
                    "module": module,
                    "action": action,
                    "slots": slots,
                }

            cmd = f"{'włącz' if desired_state == 'on' else 'wyłącz'} {device}"
            result = device_command(cmd)
            return {
                "ok": bool(result),
                "module": module,
                "action": action,
                "command": cmd,
                "result": result,
            }

        if action == "iot.blink":
            return {
                "ok": False,
                "error": "unsupported_hardware_action",
                "module": module,
                "action": action,
                "slots": slots,
                "details": "iot.blink is recognized but not implemented in hardware_bridge",
            }

        return {
            "ok": False,
            "error": "unsupported_hardware_action",
            "module": module,
            "action": action,
            "slots": slots,
        }

    if module == "system_exec":
        command = slots.get("command")
        if not command:
            return {
                "ok": False,
                "error": "missing_command",
                "module": module,
                "action": action,
                "slots": slots,
            }

        import subprocess

        try:
            proc = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return {
                "ok": proc.returncode == 0,
                "module": module,
                "action": action,
                "command": command,
                "returncode": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "module": module,
                "action": action,
                "command": command,
            }

    return {
        "ok": False,
        "error": "unsupported_plan_module",
        "module": module,
        "action": action,
        "slots": slots,
    }
