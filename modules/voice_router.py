from __future__ import annotations

from typing import Any


ROUTE_CLASSES = (
    "conversation",
    "device",
    "system",
    "youtube",
    "smart_query",
    "unsafe_candidate",
    "unknown",
)

DEVICE_KEYWORDS = {
    "światło", "światła", "lampę", "lampa", "led", "diodę", "dioda",
    "głośnik", "speaker", "shelly", "mqtt", "włącz", "wyłącz", "zgaś",
}

SYSTEM_KEYWORDS = {
    "terminal", "konsol", "bash", "shell", "komend", "uruchom program",
    "odpal", "restart", "zabij proces", "plik", "folder", "katalog",
    "skrypt", "python", "ssh", "tmux",
}

YOUTUBE_KEYWORDS = {
    "youtube", "jutub", "yt", "piosenk", "muzyk", "muzykę", "teledysk",
    "filmik", "film", "play", "pause", "skip", "następny", "poprzedni",
    "puść", "odtwórz",
}

SMART_QUERY_KEYWORDS = {
    "sprawdź", "wyszukaj", "znajdź", "poszukaj", "porównaj", "przeanalizuj",
    "przeszukaj", "search", "lookup",
}

CONVERSATION_PREFIXES = {
    "opowiedz",
    "powiedz",
    "wyjaśnij",
    "co myślisz",
    "czy",
    "jak działa",
    "dlaczego",
}

UNSAFE_PATTERNS = {
    "rm -rf",
    "mkfs",
    "dd if=",
    "shutdown",
    "reboot",
    "poweroff",
    "format",
    "usuń wszystko",
    "skasuj wszystko",
}


def _contains_any(text: str, phrases: set[str]) -> list[str]:
    hits = []
    for item in phrases:
        if item in text:
            hits.append(item)
    return sorted(hits)


def classify_voice_route(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    low = raw.lower()

    base_scores = {name: 0.0 for name in ROUTE_CLASSES}
    reasons: list[str] = []

    if not low:
        base_scores["unknown"] = 1.0
        return {
            "ok": False,
            "text": raw,
            "route": "unknown",
            "score": 1.0,
            "scores": base_scores,
            "reason": "empty",
            "matches": {},
        }

    unsafe_hits = _contains_any(low, UNSAFE_PATTERNS)
    if unsafe_hits:
        base_scores["unsafe_candidate"] += 0.95
        reasons.append(f"unsafe_pattern:{','.join(unsafe_hits)}")

    youtube_hits = _contains_any(low, YOUTUBE_KEYWORDS)
    if youtube_hits:
        base_scores["youtube"] += min(0.95, 0.40 + 0.12 * len(youtube_hits))
        reasons.append(f"youtube_keywords:{','.join(youtube_hits[:4])}")

    device_hits = _contains_any(low, DEVICE_KEYWORDS)
    if device_hits:
        base_scores["device"] += min(0.95, 0.38 + 0.12 * len(device_hits))
        reasons.append(f"device_keywords:{','.join(device_hits[:4])}")

    system_hits = _contains_any(low, SYSTEM_KEYWORDS)
    if system_hits:
        base_scores["system"] += min(0.95, 0.36 + 0.12 * len(system_hits))
        reasons.append(f"system_keywords:{','.join(system_hits[:4])}")

    smart_hits = _contains_any(low, SMART_QUERY_KEYWORDS)
    if smart_hits:
        base_scores["smart_query"] += min(0.90, 0.34 + 0.10 * len(smart_hits))
        reasons.append(f"smart_keywords:{','.join(smart_hits[:4])}")

    for prefix in CONVERSATION_PREFIXES:
        if low.startswith(prefix):
            base_scores["conversation"] += 0.72
            reasons.append(f"conversation_prefix:{prefix}")
            break

    if "?" in raw:
        base_scores["conversation"] += 0.20
        reasons.append("question_mark")

    if not any(base_scores[name] > 0 for name in ROUTE_CLASSES if name != "unknown"):
        if len(low.split()) >= 3:
            base_scores["conversation"] += 0.45
            reasons.append("fallback_natural_phrase")
        else:
            base_scores["unknown"] = 0.70
            reasons.append("fallback_unknown")

    if base_scores["youtube"] > 0 and "youtube" in low and ("włącz" in low or "puść" in low or "odtwórz" in low):
        base_scores["youtube"] = min(1.0, base_scores["youtube"] + 0.15)
        reasons.append("youtube_intent_boost")

    if (
        base_scores["youtube"] > 0
        and "youtube" in low
        and len(low.split()) >= 2
    ):
        base_scores["youtube"] = min(1.0, base_scores["youtube"] + 0.18)
        reasons.append("youtube_phrase_with_query_boost")

    if (
        base_scores["youtube"] > 0
        and "na youtube" in low
        and len(low.split()) >= 3
    ):
        base_scores["youtube"] = min(1.0, base_scores["youtube"] + 0.18)
        reasons.append("youtube_na_youtube_boost")

    if base_scores["device"] > 0 and ("włącz" in low or "wyłącz" in low or "zgaś" in low):
        base_scores["device"] = min(1.0, base_scores["device"] + 0.15)
        reasons.append("device_action_boost")

    if base_scores["system"] > 0 and ("uruchom" in low or "odpal" in low or "restart" in low):
        base_scores["system"] = min(1.0, base_scores["system"] + 0.15)
        reasons.append("system_action_boost")

    route = max(base_scores, key=base_scores.get)
    score = round(base_scores[route], 3)

    if score <= 0:
        route = "unknown"
        score = 1.0
        reasons.append("zero_score_unknown")

    reason = reasons[0] if reasons else "no_reason"

    return {
        "ok": True,
        "text": raw,
        "route": route,
        "score": score,
        "scores": {k: round(v, 3) for k, v in base_scores.items()},
        "reason": reason,
        "matches": {
            "unsafe": unsafe_hits,
            "youtube": youtube_hits,
            "device": device_hits,
            "system": system_hits,
            "smart_query": smart_hits,
        },
    }


def route_voice_text(text: str) -> dict[str, Any]:
    return classify_voice_route(text)


if __name__ == "__main__":
    raise SystemExit("voice_router.py is a module, not a standalone runner")
