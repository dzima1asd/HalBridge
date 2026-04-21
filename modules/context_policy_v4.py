from __future__ import annotations

from typing import Any


FOLLOWUP_MARKERS = {
    "to",
    "tego",
    "temu",
    "tamto",
    "tamtego",
    "go",
    "ją",
    "ja",
    "je",
    "rozwiń",
    "rozwin",
    "krócej",
    "krocej",
    "szerzej",
    "dalej",
    "a teraz",
    "a co z",
}


def looks_like_followup_text(text: str) -> bool:
    low = (text or "").strip().lower()
    if not low:
        return False

    words = [w for w in low.split() if w.strip()]
    word_set = set(words)

    for marker in FOLLOWUP_MARKERS:
        m = marker.strip().lower()
        if not m:
            continue
        if " " in m:
            if low.startswith(m):
                return True
        else:
            if m in word_set:
                return True

    return False


def choose_context_mode(
    *,
    route: str,
    text: str,
    has_session: bool = False,
    force_session: bool = False,
) -> dict[str, Any]:
    raw = (text or "").strip()
    low = raw.lower()
    words = [w for w in low.split() if w.strip()]

    if force_session:
        return {
            "mode": "session",
            "reason": "forced_session",
        }

    if route in {"device", "youtube", "system", "unsafe_candidate"}:
        return {
            "mode": "stateless",
            "reason": "non_conversation_route",
        }

    if route in {"conversation", "smart_query"}:
        if len(words) <= 4 and not has_session:
            return {
                "mode": "stateless",
                "reason": "short_without_session",
            }

        if any(marker in low for marker in FOLLOWUP_MARKERS) and has_session:
            return {
                "mode": "light",
                "reason": "followup_with_session",
            }

        if len(words) <= 8:
            return {
                "mode": "light",
                "reason": "short_conversation",
            }

        return {
            "mode": "session",
            "reason": "long_conversation",
        }

    return {
        "mode": "light",
        "reason": "default_light",
    }
