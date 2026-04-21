from __future__ import annotations
from modules.intents.recognizer import recognize_intent
from modules.intents.extract_slots import extract_slots
from modules.policy.router import route
from modules.guardrails import preflight
from modules.self_heal import try_self_heal
from modules.metrics import (
    stat_intent_ok,
    stat_intent_fail,
    stat_slot_fill,
    stat_slot_missing,
)
from modules.dialog.manager_v2 import ask_for_missing_slots

SUPPORTED_PLAN_MODULES = {
    "hardware_bridge",
    "system_exec",
}


def intent_pipeline(user_text):
    intent_info = recognize_intent(user_text)
    intent = intent_info.get("intent")

    if not intent:
        stat_intent_fail()
        return {"error": "unknown_intent"}

    stat_intent_ok()

    slots = extract_slots(user_text, intent)
    if slots:
        stat_slot_fill()
    else:
        stat_slot_missing()

    required = []
    if intent.startswith("iot."):
        required = ["device"]
    elif intent == "mail.search":
        required = ["query"]
    elif intent == "browser.fetch":
        required = ["query"]
    elif intent == "system.exec":
        required = ["command"]
    missing = [r for r in required if r not in slots]
    ask = ask_for_missing_slots(required, slots)
    if ask:
        return {
            "ask": ask,
            "intent": intent,
            "slots": slots,
            "missing_slots": missing,
        }

    plan = route(intent, slots)

    if plan.get("module") not in SUPPORTED_PLAN_MODULES:
        return {
            "error": "unsupported_plan_module",
            "plan": plan,
        }

    pf = preflight(plan)

    if not pf.get("ok"):
        healed = try_self_heal(intent, plan, pf)
        if healed.get("ok"):
            plan["slots"] = healed["slots"]
        else:
            return {"error": pf}

    return {"plan": plan}
