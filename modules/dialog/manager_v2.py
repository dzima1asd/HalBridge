def ask_for_missing_slots(required, slots):
    missing = [r for r in required if r not in slots]
    if not missing:
        return None

    field = missing[0]

    prompts = {
        "device": "Jakie urządzenie mam sterować?",
        "time": "Podaj czas.",
        "duration": "Jak długo ma to trwać?",
        "on_ms": "Ile milisekund ma świecić?",
        "off_ms": "Ile milisekund ma gasnąć?"
    }

    return prompts.get(field, f"Brakuje parametru: {field}")
