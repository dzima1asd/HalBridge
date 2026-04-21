from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def default_session_state() -> dict[str, Any]:
    return {
        "active": False,
        "started_at": None,
        "expires_at": None,
        "last_wake_word": None,
        "last_route": None,
        "turn_count": 0,
    }


def start_voice_session(
    *,
    timeout_seconds: int = 20,
    wake_word: str | None = None,
    route: str | None = None,
) -> dict[str, Any]:
    now = utc_now()
    expires = now + timedelta(seconds=max(1, int(timeout_seconds)))
    return {
        "active": True,
        "started_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "last_wake_word": wake_word,
        "last_route": route,
        "turn_count": 0,
    }


def end_voice_session(session: dict[str, Any] | None = None) -> dict[str, Any]:
    state = dict(default_session_state())
    if session:
        state.update(session)
    state["active"] = False
    state["expires_at"] = None
    return state


def is_session_active(session: dict[str, Any] | None = None, *, now: datetime | None = None) -> bool:
    if not session:
        return False
    if not session.get("active"):
        return False

    current = now or utc_now()
    expires_at = parse_iso(session.get("expires_at"))
    if not expires_at:
        return False

    return current < expires_at


def touch_voice_session(
    session: dict[str, Any] | None,
    *,
    timeout_seconds: int = 20,
    route: str | None = None,
) -> dict[str, Any]:
    if not session or not is_session_active(session):
        return start_voice_session(timeout_seconds=timeout_seconds, route=route)

    updated = dict(session)
    updated["expires_at"] = (utc_now() + timedelta(seconds=max(1, int(timeout_seconds)))).isoformat()
    updated["turn_count"] = int(updated.get("turn_count", 0)) + 1
    if route:
        updated["last_route"] = route
    return updated


def wake_needed_for_text(
    *,
    route: str | None,
    wake_required_by_policy: bool,
    session: dict[str, Any] | None = None,
) -> bool:
    if not wake_required_by_policy:
        return False

    if is_session_active(session):
        return False

    return True


if __name__ == "__main__":
    raise SystemExit("voice_session.py is a module, not a standalone runner")
