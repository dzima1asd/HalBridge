from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PREFERENCES_PATH = Path("state/voice_preferences.json")

DEFAULTS: dict[str, Any] = {
    "media_auto_execute": False,
    "device_proposal_auto_execute": False,
}


def load_voice_preferences() -> dict[str, Any]:
    try:
        data = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
    except Exception:
        pass
    return dict(DEFAULTS)


def save_voice_preferences(data: dict[str, Any]) -> None:
    merged = dict(DEFAULTS)
    merged.update(data or {})
    PREFERENCES_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFERENCES_PATH.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_voice_preference(name: str, default: Any = None) -> Any:
    prefs = load_voice_preferences()
    return prefs.get(name, default)


def set_voice_preference(name: str, value: Any) -> dict[str, Any]:
    prefs = load_voice_preferences()
    prefs[name] = value
    save_voice_preferences(prefs)
    return prefs
