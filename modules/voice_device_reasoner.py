from __future__ import annotations

from typing import Dict
from pathlib import Path
import json

STATE_PATH = Path("~/.local/share/halbridge/hw_context.json").expanduser()


def _norm(s: str) -> str:
    return (
        (s or "").strip().lower()
        .replace("ś", "s").replace("ą", "a").replace("ł", "l")
        .replace("ó", "o").replace("ć", "c").replace("ę", "e")
        .replace("ń", "n").replace("ż", "z").replace("ź", "z")
    )


def get_device_state(name: str) -> str:
    key = _norm(name)

    if not STATE_PATH.exists():
        return "unknown"

    try:
        data = json.load(open(STATE_PATH, "r", encoding="utf-8"))
    except:
        return "unknown"

    return data.get("state", {}).get(key, "unknown")


def reason_about_device_word(text: str) -> Dict:
    low = (text or "").strip().lower()

    if low in ("światło", "swiatlo"):
        state = get_device_state("swiatlo 2")

        if state == "off":
            return {
                "mode": "propose_action",
                "route": "device",
                "execute_text": "włącz światło 2",
                "reply_text": "Jest ciemno. Włączyć światło 2?",
                "reason": "device_state_light_off",
                "confidence": 0.85,
            }

        if state == "on":
            return {
                "mode": "propose_action",
                "route": "device",
                "execute_text": "wyłącz światło 2",
                "reply_text": "Światło jest włączone. Wyłączyć?",
                "reason": "device_state_light_on",
                "confidence": 0.85,
            }

        # fallback
        return {
            "mode": "propose_action",
            "route": "device",
            "execute_text": "włącz światło 2",
            "reply_text": "Nie znam stanu światła. Włączyć?",
            "reason": "device_state_unknown",
            "confidence": 0.6,
        }

    return {}
