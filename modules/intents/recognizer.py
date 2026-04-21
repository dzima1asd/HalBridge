import re

INTENT_PATTERNS = {
    "iot.toggle": [
        r"\b(włącz|wlacz|wyłącz|wylacz|toggle)\b",
    ],
    "iot.blink": [
        r"\b(mrugaj|migaj|blink|mruganie)\b",
    ],
    "data.analyze": [
        r"\b(analizuj|analiza|przeanalizuj)\b",
    ],
    "browser.fetch": [
        r"\b(pobierz stronę|pobierz strone|fetch)\b",
    ],
    "mail.search": [
        r"\b(znajdź w mailach|znajdz w mailach|szukaj maili|szukaj w mailach)\b",
    ],
    "system.exec": [
        r"\b(wykonaj komendę|wykonaj komende|uruchom komendę|uruchom komende|system)\b",
    ],
}

def recognize_intent(text: str):
    text_l = (text or "").lower().strip()

    for intent, patterns in INTENT_PATTERNS.items():
        for p in patterns:
            if re.search(p, text_l):
                return {"intent": intent, "confidence": 0.9}

    if re.search(r"\b(włącz|wyłącz|wlacz|wylacz)\b", text_l):
        return {"intent": "iot.toggle", "confidence": 0.6}

    if re.search(r"\b(mrugaj|migaj|blink|mruganie)\b", text_l):
        return {"intent": "iot.blink", "confidence": 0.6}

    return {"intent": None, "confidence": 0.0}
