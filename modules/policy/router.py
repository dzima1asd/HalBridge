def route(intent: str, slots: dict):
    if intent.startswith("iot."):
        return {"module": "hardware_bridge", "action": intent, "slots": slots}

    if intent.startswith("data."):
        return {"module": "code", "action": intent, "slots": slots}

    if intent.startswith("browser."):
        return {"module": "browser_controller", "action": intent, "slots": slots}

    if intent.startswith("mail."):
        return {"module": "gmail_bridge", "action": intent, "slots": slots}

    if intent.startswith("system."):
        return {"module": "system_exec", "action": intent, "slots": slots}

    return {"module": None, "error": "unknown_intent"}

