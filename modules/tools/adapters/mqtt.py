def spec():
    return {
        "name": "mqtt",
        "description": "MQTT actuator stub",
        "input": {"topic": "string", "payload": "dict"},
        "output": {"ok": "boolean"}
    }

def invoke(payload: dict):
    topic = payload.get("topic")
    msg = payload.get("payload")
    if not topic:
        return {"ok": False, "error": "missing_topic"}

    # Stub – logujemy wywołanie, udajemy sukces
    return {
        "ok": True,
        "sent": {"topic": topic, "payload": msg}
    }
