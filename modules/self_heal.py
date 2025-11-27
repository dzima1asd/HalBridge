import json
from datetime import datetime

SELF_HEAL_LOG = "/home/hal/HALbridge/auto_patch.log"

def log_event(data):
    with open(SELF_HEAL_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")

def try_self_heal(intent: str, plan: dict, error: dict):
    action = plan.get("action", "")
    slots = plan.get("slots", {})

    # Przykład 1 – naprawa nieistniejącego urządzenia
    if "missing_device" in error.get("error", ""):
        slots["device"] = "światło 1"
        log_event({
            "time": datetime.now().isoformat(),
            "intent": intent,
            "fix": "assign_default_device",
            "new_slots": slots
        })
        return {"ok": True, "slots": slots}

    # Przykład 2 – brak czasu → ustaw domyślnie "natychmiast"
    if "missing_time" in error.get("error", ""):
        slots["time"] = "now"
        log_event({
            "time": datetime.now().isoformat(),
            "intent": intent,
            "fix": "assign_default_time",
            "new_slots": slots
        })
        return {"ok": True, "slots": slots}

    # nic nie naprawiono
    log_event({
        "time": datetime.now().isoformat(),
        "intent": intent,
        "fix": "none",
        "error": error
    })
    return {"ok": False}
