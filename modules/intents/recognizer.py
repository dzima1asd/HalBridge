import re

INTENT_KEYWORDS = {
    "iot.toggle": ["włącz", "wlacz", "wyłącz", "wylacz", "toggle"],
    "iot.blink": ["mrugaj", "migaj", "blink"],
    "data.analyze": ["analizuj", "analiza", "przeanalizuj"],
    "browser.fetch": ["pobierz stronę", "pobierz strone", "fetch"],
    "mail.search": ["znajdź w mailach", "szukaj maili", "mail"],
    "system.exec": ["uruchom", "wykonaj", "system"],
}

def recognize_intent(text: str):
    text_l = text.lower()

    # słownikowe dopasowanie
    for intent, words in INTENT_KEYWORDS.items():
        for w in words:
            if w in text_l:
                return {"intent": intent, "confidence": 0.9}

    # fallback regex
    if re.search(r"\b(włącz|wyłącz|wlacz|wylacz)\b", text_l):
        return {"intent": "iot.toggle", "confidence": 0.6}

    if re.search(r"\bmrug(a|aj|anie)\b", text_l):
        return {"intent": "iot.blink", "confidence": 0.6}

    # nic nie znaleziono
    return {"intent": None, "confidence": 0.0}
