from datetime import datetime

METRICS_FILE = "/home/hal/HALbridge/intent_metrics.json"

import json
import os

def _load():
    if not os.path.exists(METRICS_FILE):
        return {"intent_ok": 0, "intent_fail": 0, "slot_fill": 0, "slot_missing": 0}
    return json.loads(open(METRICS_FILE).read())

def _save(data):
    with open(METRICS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def stat_intent_ok():
    m = _load()
    m["intent_ok"] += 1
    _save(m)

def stat_intent_fail():
    m = _load()
    m["intent_fail"] += 1
    _save(m)

def stat_slot_fill():
    m = _load()
    m["slot_fill"] += 1
    _save(m)

def stat_slot_missing():
    m = _load()
    m["slot_missing"] += 1
    _save(m)

def load_all():
    return _load()
