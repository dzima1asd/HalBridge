def simulate_iot(plan: dict):
    slots = plan.get("slots", {})
    if "device" not in slots:
        return {"ok": False, "error": "missing_device"}

    return {
        "ok": True,
        "simulation": f"IoT action '{plan['action']}' on {slots['device']}"
    }
