from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

DEVICE_COMMANDS_PATH = Path("device_commands.json")

LIGHT_HINTS = ("światło", "swiatlo", "lampa", "dioda", "led")
HEAT_HINTS = ("grzejnik", "kaloryfer", "ogrzewanie", "temperatura")
MEDIA_HINTS = ("youtube", "jutub", "głośnik", "glosnik", "speaker")


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def _load_device_commands() -> dict[str, Any]:
    try:
        data = json.loads(DEVICE_COMMANDS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _action_aliases(spec: Any) -> set[str]:
    actions: set[str] = set()
    if isinstance(spec, dict):
        for key in spec.keys():
            low = _norm(str(key))
            if low in {"włącz", "wlacz"}:
                actions.add("on")
            elif low in {"wyłącz", "wylacz", "zgaś", "zgas"}:
                actions.add("off")
            elif low == "status":
                actions.add("status")
    else:
        actions.add("trigger")
    return actions


def list_capabilities() -> list[dict[str, Any]]:
    data = _load_device_commands()
    caps: list[dict[str, Any]] = []

    for name, spec in data.items():
        display = str(name).strip()
        low = _norm(display)
        actions = sorted(_action_aliases(spec))
        tags: list[str] = []
        preferred_rank = 50

        if any(h in low for h in LIGHT_HINTS):
            tags.append("light")
            if re.search(r"\b2\b", low):
                preferred_rank = 10
            elif re.search(r"\b1\b", low):
                preferred_rank = 20

        if any(h in low for h in HEAT_HINTS):
            tags.append("heat")

        if any(h in low for h in MEDIA_HINTS):
            tags.append("media")

        caps.append({
            "id": re.sub(r"[^a-z0-9]+", "_", low).strip("_") or "capability",
            "name": display,
            "normalized_name": low,
            "tags": tags,
            "actions": actions,
            "execute_on": f"włącz {display}" if "on" in actions else "",
            "execute_off": f"wyłącz {display}" if "off" in actions else "",
            "preferred_rank": preferred_rank,
        })

    return caps


def best_capability_for_tag(tag: str) -> dict[str, Any] | None:
    matches = [c for c in list_capabilities() if tag in c.get("tags", [])]
    if not matches:
        return None
    matches.sort(key=lambda c: (int(c.get("preferred_rank", 50) or 50), c.get("name", "")))
    return matches[0]


def capability_snapshot(max_items: int = 12) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for cap in list_capabilities()[:max_items]:
        out.append({
            "name": cap.get("name", ""),
            "tags": list(cap.get("tags", [])),
            "actions": list(cap.get("actions", [])),
        })
    return out
