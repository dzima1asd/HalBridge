from __future__ import annotations

LOCATION_ALIASES = {
    "białystok": ["białystok", "białymstoku", "bialystok", "bialymstoku"],
    "warszawa": ["warszawa", "warszawie"],
    "poznań": ["poznań", "poznaniu", "poznan", "poznaniu"],
    "kraków": ["kraków", "krakowie", "krakow", "krakowie"],
    "wrocław": ["wrocław", "wrocławiu", "wroclaw", "wroclawiu"],
    "gdańsk": ["gdańsk", "gdańsku", "gdansk", "gdansku"],
    "lublin": ["lublin", "lublinie"],
    "olsztyn": ["olsztyn", "olsztynie"],
    "szczecin": ["szczecin", "szczecinie"],
    "łódź": ["łódź", "łodzi", "lodz", "lodzi"],
    "katowice": ["katowice", "katowicach"],
    "gdynia": ["gdynia", "gdyni"],
    "sopot": ["sopot", "sopocie"],
    "toruń": ["toruń", "toruniu", "torun", "toruniu"],
    "rzeszów": ["rzeszów", "rzeszowie", "rzeszow", "rzeszowie"],
    "bydgoszcz": ["bydgoszcz", "bydgoszczy"],
}

def normalize_location(text: str | None) -> str | None:
    q = (text or "").strip().lower()
    if not q:
        return None
    for canonical, forms in LOCATION_ALIASES.items():
        if any(f in q for f in forms):
            return canonical
    return None
