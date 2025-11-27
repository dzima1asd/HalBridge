def preflight(plan: dict):
    if not plan.get("module"):
        return {"ok": False, "error": "no_module"}

    if plan.get("action", "").startswith("iot."):
        slots = plan.get("slots", {})
        if "device" not in slots:
            return {"ok": False, "error": "iot_missing_device"}

    return {"ok": True}
