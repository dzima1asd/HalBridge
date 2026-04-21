from __future__ import annotations

from typing import Any, Dict


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def _is_affirmative(text: str) -> bool:
    low = _norm(text)

    if not low:
        return False

    yes_tokens = (
        "tak",
        "ok",
        "okej",
        "jasne",
        "dobra",
        "spoko",
    )

    # jeśli zaczyna się od zgody → traktujemy jako confirm
    return any(low.startswith(tok) for tok in yes_tokens)


def _wants_automatic_behavior(text: str) -> bool:
    low = _norm(text)

    if not low:
        return False

    # zamiast gotowych zdań → patrzymy na kombinacje sensów
    auto_tokens = (
        "automatycznie",
        "od razu",
        "bez pytania",
        "bez pytaj",
        "nie pytaj",
        "następnym razem",
        "na przyszłość",
        "na przyszlosc",
    )

    return any(tok in low for tok in auto_tokens)


def reason_about_preference(
    text: str,
    pending_action: dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Zwraca interpretację zgody i preferencji.

    Nie wykonuje akcji. Nie zna urządzeń.
    Tylko interpretuje intencję użytkownika.
    """

    low = _norm(text)

    confirm_now = _is_affirmative(low)

    wants_auto = _wants_automatic_behavior(low)

    result: Dict[str, Any] = {
        "confirm_now": confirm_now,
        "save_preference": False,
        "preference_name": None,
        "preference_value": None,
        "confidence": 0.5,
    }

    if confirm_now and wants_auto:
        pending_route = str((pending_action or {}).get("route") or "").strip().lower()

        if pending_route == "youtube":
            pref_name = "media_auto_execute"
        elif pending_route == "device":
            pref_name = "device_proposal_auto_execute"
        else:
            pref_name = None

        if pref_name:
            result.update({
                "save_preference": True,
                "preference_name": pref_name,
                "preference_value": True,
                "confidence": 0.8,
            })

    return result
