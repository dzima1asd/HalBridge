from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_LOG_PATH = Path.home() / "HALbridge/state/voice_events.jsonl"

KNOWN_EVENTS = {
    "runtime_started",
    "speech_started",
    "speech_ended",
    "segment_recorded",
    "stt_result",
    "route_selected",
    "dispatch_selected",
    "daemon_result",
    "cooldown_entered",
    "error",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_voice_event(
    event: str,
    *,
    source: str,
    current_state: str | None = None,
    transcript: str | None = None,
    route: str | None = None,
    action_taken: str | None = None,
    reply_text: str | None = None,
    error: str | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ts": utc_now_iso(),
        "event": event,
        "source": source,
        "current_state": current_state,
        "transcript": transcript,
        "route": route,
        "action_taken": action_taken,
        "reply_text": reply_text,
        "error": error,
        "data": data or {},
    }


def log_voice_event(
    event: str,
    *,
    source: str,
    current_state: str | None = None,
    transcript: str | None = None,
    route: str | None = None,
    action_taken: str | None = None,
    reply_text: str | None = None,
    error: str | None = None,
    data: dict[str, Any] | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    path = Path(log_path) if log_path else DEFAULT_LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = build_voice_event(
        event,
        source=source,
        current_state=current_state,
        transcript=transcript,
        route=route,
        action_taken=action_taken,
        reply_text=reply_text,
        error=error,
        data=data,
    )

    path.write_text("", encoding="utf-8") if not path.exists() else None
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "event": event,
        "known_event": event in KNOWN_EVENTS,
        "log_path": str(path),
        "ts": payload["ts"],
    }


def read_last_voice_events(
    limit: int = 20,
    *,
    log_path: str | None = None,
) -> list[dict[str, Any]]:
    path = Path(log_path) if log_path else DEFAULT_LOG_PATH
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[dict[str, Any]] = []

    for line in lines[-max(1, int(limit)):]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({
                "ts": utc_now_iso(),
                "event": "error",
                "source": "voice_logger",
                "current_state": None,
                "transcript": None,
                "route": None,
                "action_taken": None,
                "reply_text": None,
                "error": "invalid_jsonl_line",
                "data": {"raw": line},
            })
    return out


if __name__ == "__main__":
    raise SystemExit("voice_logger.py is a module, not a standalone runner")
