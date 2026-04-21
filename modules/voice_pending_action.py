from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

PENDING_PATH = Path("state/voice_pending_action.json")
PENDING_TTL_SECONDS = 20

AFFIRMATIVE = {"tak", "ta", "okej", "ok", "jasne", "dobra", "zgoda", "potwierdzam"}
NEGATIVE = {"nie", "cancel", "anuluj", "zostaw", "nieważne", "niewazne"}


def _norm(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def save_pending_action(data: dict[str, Any]) -> None:
    payload = dict(data or {})
    payload["ts"] = time.time()
    PENDING_PATH.parent.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_pending_action() -> None:
    try:
        PENDING_PATH.unlink()
    except FileNotFoundError:
        pass


def load_pending_action() -> dict[str, Any] | None:
    try:
        data = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
        ts = float(data.get("ts", 0) or 0)
        if (time.time() - ts) > PENDING_TTL_SECONDS:
            clear_pending_action()
            return None
        return data
    except Exception:
        return None


def is_affirmative(text: str) -> bool:
    low = _norm(text)
    if not low:
        return False
    first = low.split()[0]
    return first in AFFIRMATIVE


def is_negative(text: str) -> bool:
    low = _norm(text)
    if not low:
        return False
    first = low.split()[0]
    return first in NEGATIVE
