#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shelly MQTT Listener (V2)
Aktualizuje stan świateł w hw_context.json w formacie
ZNORMALIZOWANYM (swiatlo 1, swiatlo 2).
"""

import json
import paho.mqtt.client as mqtt
from pathlib import Path

STATE_PATH = Path("~/.local/share/halbridge/hw_context.json").expanduser()

SHELLY_ID = "shellyplus2pm-c4d8d5560dcc"
TOPIC = f"{SHELLY_ID}/events/rpc"

def _slug(s):
    import re
    return re.sub(r"\s+", " ", (s or "").strip().lower())

def _norm(s):
    return _slug(s).replace("ś", "s").replace("ą", "a").replace("ł", "l").replace("ó", "o").replace("ć", "c").replace("ę", "e").replace("ń", "n").replace("ż", "z").replace("ź", "z")

def load_state():
    if not STATE_PATH.exists():
        return {"state": {}, "state_source": {}}
    try:
        return json.load(open(STATE_PATH, "r", encoding="utf-8"))
    except:
        return {"state": {}, "state_source": {}}

def save_state(state_obj):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state_obj, f, indent=2, ensure_ascii=False)

def on_message(c, u, msg):
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except:
        return

    method = payload.get("method")
    params = payload.get("params", {})

    if method != "NotifyStatus":
        return

    sw0 = params.get("switch:0")
    sw1 = params.get("switch:1")

    st = load_state()

    # Normalizowane klucze
    dev1 = _norm("swiatlo 1")
    dev2 = _norm("swiatlo 2")

    if sw0 and "output" in sw0:
        st["state"][dev1] = "on" if sw0["output"] else "off"
        st["state_source"][dev1] = "mqtt"

    if sw1 and "output" in sw1:
        st["state"][dev2] = "on" if sw1["output"] else "off"
        st["state_source"][dev2] = "mqtt"

    save_state(st)

def main():
    client = mqtt.Client()
    print("[SHELLY] łączę z MQTT...")
    client.connect("192.168.100.12", 1883, 60)
    client.subscribe(TOPIC)
    client.on_message = on_message
    print("[SHELLY] słucham:", TOPIC)
    client.loop_forever()

if __name__ == "__main__":
    main()
