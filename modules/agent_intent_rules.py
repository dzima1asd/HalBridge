from __future__ import annotations

import re


def ai_intent(user_query: str) -> dict:
    """
    Określa, czy pytanie wymaga internetu — wersja regułowa.
    Brak tokenów. Zero LLM. Twarde reguły.
    """
    q = user_query.strip().lower()

    NEWS_KEYWORDS = [
        "co się wydarzyło", "co sie wydarzylo", "co nowego",
        "najnowsze", "wiadomości", "newsy", "informacje",
        "sytuacja w", "breaking", "aktualne", "co obecnie",
        "co teraz", "co dzisiaj", "co w polsce", "co w usa",
        "raport", "zdarzenia", "wydarzenia", "sytuacja polityczna",
        "inflacja", "gospodarka dziś", "ekonomia dziś",
    ]

    if any(k in q for k in NEWS_KEYWORDS):
        return {"need_web": True, "queries": [user_query]}

    DATE_PATTERNS = [
        r"\d{1,2}\s+\w+",
        r"\d{1,2}\.\d{1,2}\.\d{4}",
        r"\d{1,2}/\d{1,2}/\d{4}",
        r"\d{4}",
    ]
    if any(re.search(p, q) for p in DATE_PATTERNS):
        return {"need_web": True, "queries": [user_query]}

    LOCAL_KEYWORDS = [
        "jak działa", "z czego zbudowany", "z jakich części",
        "co to jest", "wyjaśnij", "definicja",
        "ile to jest", "oblicz", "matematyka", "fizyka",
        "chemia", "mechanizm", "działanie", "opis konstrukcji",
        "karabin", "silnik", "komputer", "algorytm",
        "python", "linux", "bash",
    ]

    if any(k in q for k in LOCAL_KEYWORDS):
        return {"need_web": False, "queries": [user_query]}

    HISTORY_KEYWORDS = [
        "historia", "kim był", "kiedy żył", "starożytność",
        "średniowiecze", "bitwa", "cesarz", "król",
        "dlaczego doszło", "tło historyczne",
    ]
    if any(k in q for k in HISTORY_KEYWORDS):
        return {"need_web": False, "queries": [user_query]}

    BUSINESS_KEYWORDS = [
        "cena", "kosztuje", "kurs", "notowania",
        "ile kosztuje", "prognoza", "firma", "spółka",
        "rynek", "amazon", "tesla", "allegro",
    ]
    if any(k in q for k in BUSINESS_KEYWORDS):
        return {"need_web": True, "queries": [user_query]}

    return {"need_web": False, "queries": [user_query]}
