from __future__ import annotations

from typing import Any

from modules.voice_capabilities import best_capability_for_tag

DARKNESS_CUES = (
    "ciemno", "za ciemno", "nie widzę", "nie widze", "nic nie widzę", "nic nie widze",
)
COLD_CUES = (
    "zimno", "zmarzłem", "zmarzlem", "chłodno", "chlodno", "jest zimno",
)
EMOTIONAL_OUTBURSTS = {
    "kurwa", "kurwa mać", "kurwa mac", "ja pierdole", "o kurwa", "cholera",
}


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _contains_any(low: str, phrases: tuple[str, ...]) -> bool:
    return any(p in low for p in phrases)


def reason_about_voice_utterance(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    low = _norm(raw)
    if not low:
        return {"mode": "none"}

    if low in EMOTIONAL_OUTBURSTS:
        return {"mode": "none", "reason": "emotional_outburst"}

    light = best_capability_for_tag("light")
    if _contains_any(low, DARKNESS_CUES) and light and light.get("execute_on"):
        return {
            "mode": "propose_action",
            "route": "device",
            "execute_text": light["execute_on"],
            "reply_text": f"Mogę włączyć {light['name']}. Włączyć?",
            "reason": "situation_darkness",
            "confidence": 0.86,
        }

    heat = best_capability_for_tag("heat")
    if _contains_any(low, COLD_CUES) and heat and heat.get("execute_on"):
        return {
            "mode": "propose_action",
            "route": "device",
            "execute_text": heat["execute_on"],
            "reply_text": f"Mogę włączyć {heat['name']}. Włączyć?",
            "reason": "situation_cold",
            "confidence": 0.82,
        }

    return {"mode": "none"}
