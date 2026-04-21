from __future__ import annotations

from typing import Any


DEFAULT_WAKE_ALIASES = [
    "hal",
    "chal",
    "kal",
    "halu",
    "helu",
]

STRICT_ROUTE_CLASSES = {
    "device",
    "system",
    "unsafe_candidate",
}


def _normalize_wake_aliases(active_wake_words: list[str] | None = None) -> list[str]:
    aliases: list[str] = []
    seen = set()

    for item in (active_wake_words or []):
        low = (item or "").strip().lower()
        if low and low not in seen:
            aliases.append(low)
            seen.add(low)

    for item in DEFAULT_WAKE_ALIASES:
        if item not in seen:
            aliases.append(item)
            seen.add(item)

    return aliases


def _strip_leading_wake(text: str, aliases: list[str]) -> tuple[bool, str, str | None]:
    low = text.lower().strip()

    for alias in aliases:
        if low == alias:
            return True, "", alias
        if low.startswith(alias + " "):
            stripped = text[len(alias):].strip()
            return True, stripped, alias

    return False, text.strip(), None


def wake_policy_required(
    route_class: str | None,
    *,
    require_wake_for_device: bool = True,
    require_wake_for_system: bool = True,
) -> bool:
    route = (route_class or "").strip().lower()

    if route == "device":
        return bool(require_wake_for_device)

    if route == "system":
        return bool(require_wake_for_system)

    if route in STRICT_ROUTE_CLASSES:
        return True

    return False


def analyze_wake(
    text: str,
    *,
    active_wake_words: list[str] | None = None,
    route_class: str | None = None,
    require_wake_for_device: bool = True,
    require_wake_for_system: bool = True,
) -> dict[str, Any]:
    original = (text or "").strip()
    aliases = _normalize_wake_aliases(active_wake_words)

    if not original:
        return {
            "ok": False,
            "text": "",
            "wake_detected": False,
            "wake_word": None,
            "stripped_text": "",
            "wake_required": wake_policy_required(
                route_class,
                require_wake_for_device=require_wake_for_device,
                require_wake_for_system=require_wake_for_system,
            ),
            "allowed": False,
            "reason": "empty",
            "aliases": aliases,
            "route_class": route_class,
        }

    wake_detected, stripped_text, wake_word = _strip_leading_wake(original, aliases)
    wake_required = wake_policy_required(
        route_class,
        require_wake_for_device=require_wake_for_device,
        require_wake_for_system=require_wake_for_system,
    )

    if wake_required and not wake_detected:
        return {
            "ok": False,
            "text": original,
            "wake_detected": False,
            "wake_word": None,
            "stripped_text": original,
            "wake_required": True,
            "allowed": False,
            "reason": "wake_required_missing",
            "aliases": aliases,
            "route_class": route_class,
        }

    final_text = stripped_text if wake_detected else original
    final_text = final_text.strip()

    if wake_detected and not final_text:
        return {
            "ok": False,
            "text": original,
            "wake_detected": True,
            "wake_word": wake_word,
            "stripped_text": "",
            "wake_required": wake_required,
            "allowed": False,
            "reason": "wake_only",
            "aliases": aliases,
            "route_class": route_class,
        }

    return {
        "ok": True,
        "text": original,
        "wake_detected": wake_detected,
        "wake_word": wake_word,
        "stripped_text": final_text,
        "wake_required": wake_required,
        "allowed": True,
        "reason": "ok",
        "aliases": aliases,
        "route_class": route_class,
    }


def detect_wake_word(
    text: str,
    active_wake_words: list[str] | None = None,
) -> dict[str, Any]:
    return analyze_wake(
        text,
        active_wake_words=active_wake_words,
        route_class=None,
        require_wake_for_device=False,
        require_wake_for_system=False,
    )


if __name__ == "__main__":
    raise SystemExit("voice_wake.py is a module, not a standalone runner")
