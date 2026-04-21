from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_RUNTIME_STATUS_PATH = Path.home() / "HALbridge/state/voice_runtime_status.json"

DEFAULT_RUNTIME_STATUS = {
    "current_state": "idle",
    "last_transcript": "",
    "last_route": None,
    "action_taken": None,
    "last_reply_text": None,
    "last_error": None,
    "last_audio_device": None,
    "mic_health": "unknown",
    "vad_health": "unknown",
    "stt_health": "unknown",
    "segment_path": None,
    "cooldown_until": None,
    "session": {
        "active": False,
        "started_at": None,
        "expires_at": None,
        "last_wake_word": None,
        "last_route": None,
        "turn_count": 0,
    },
    "hotword": {
        "backend": None,
        "available": False,
        "detected": False,
        "score": 0.0,
        "reason": None,
    },
    "timestamps": {
        "updated_at": None,
        "speech_started_at": None,
        "speech_ended_at": None,
        "transcribed_at": None,
        "routed_at": None,
        "executed_at": None,
        "error_at": None,
    },
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_runtime_status(status_path: str | None = None) -> dict[str, Any]:
    path = Path(status_path) if status_path else DEFAULT_RUNTIME_STATUS_PATH
    if not path.exists():
        data = dict(DEFAULT_RUNTIME_STATUS)
        data["timestamps"] = dict(DEFAULT_RUNTIME_STATUS["timestamps"])
        return data

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = dict(DEFAULT_RUNTIME_STATUS)
        data["timestamps"] = dict(DEFAULT_RUNTIME_STATUS["timestamps"])
        data["last_error"] = "runtime_status_read_error"
        data["timestamps"]["error_at"] = utc_now_iso()
        return data

    merged = _deep_merge(DEFAULT_RUNTIME_STATUS, raw)
    merged["timestamps"]["updated_at"] = merged["timestamps"].get("updated_at") or utc_now_iso()
    return merged


def save_runtime_status(
    status: dict[str, Any],
    status_path: str | None = None,
) -> dict[str, Any]:
    path = Path(status_path) if status_path else DEFAULT_RUNTIME_STATUS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = _deep_merge(DEFAULT_RUNTIME_STATUS, status)
    merged["timestamps"]["updated_at"] = utc_now_iso()

    path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "status_path": str(path),
        "current_state": merged.get("current_state"),
        "updated_at": merged["timestamps"]["updated_at"],
    }


def mark_runtime_state(
    current_state: str,
    *,
    status_path: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    status = load_runtime_status(status_path)
    status["current_state"] = current_state
    for key, value in fields.items():
        status[key] = value
    return save_runtime_status(status, status_path)


def mark_runtime_error(
    error: str,
    *,
    status_path: str | None = None,
    current_state: str = "error",
    **fields: Any,
) -> dict[str, Any]:
    status = load_runtime_status(status_path)
    status["current_state"] = current_state
    status["last_error"] = error
    status["timestamps"]["error_at"] = utc_now_iso()
    for key, value in fields.items():
        status[key] = value
    return save_runtime_status(status, status_path)


if __name__ == "__main__":
    raise SystemExit("voice_runtime_state.py is a module, not a standalone runner")
