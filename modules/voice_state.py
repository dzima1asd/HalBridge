from __future__ import annotations

import json
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path.home() / "HALbridge/state/voice_state.json"

DEFAULT_STATE = {
    "hardware_dry_run": True,
    "default_record_seconds": 4,
    "active_wake_words": ["hal", "komenda"],
    "listener_device": "plughw:VX800,0",
    "listener_rate": 16000,
    "listener_channels": 1,
    "listener_sample_width": 2,
    "stt_model_path": "/home/hal/models/vosk/vosk-model-small-pl-0.22",
    "hybrid_stt_enabled": True,
    "hybrid_stt_youtube_enabled": True,
    "stt_model_path_en": "/home/hal/models/vosk/vosk-model-small-en-us-0.15",
    "hybrid_stt_debug": True,
    "intent_assist_mode": "off",
    "intent_assist_provider": "api",
    "intent_assist_api_limit": 100,
    "intent_assist_api_calls_total": 0,

    "voice_mode": "runtime_v2",
    "vad_enabled": True,
    "vad_aggressiveness": 2,
    "vad_frame_ms": 30,
    "vad_energy_threshold": 450,
    "speech_start_frames": 2,
    "speech_end_frames": 6,
    "speech_start_ms": 60,
    "speech_end_silence_ms": 180,
    "pre_roll_frames": 5,
    "max_segment_seconds": 8,
    "max_idle_seconds": 10,
    "cooldown_ms": 800,
    "require_wake_for_device": True,
    "require_wake_for_system": True,
    "tts_enabled": True,
    "tts_provider": "piper",
    "tts_fx_mode": "standard",
    "tts_model_path": "/home/hal/models/piper/pl_PL-gosia-medium.onnx",
    "tts_model_config_path": "/home/hal/models/piper/pl_PL-gosia-medium.onnx.json",
    "hotword_enabled": False,
    "hotword_backend": "openwakeword",
    "hotword_threshold": 0.5,
    "hotword_gate_frames": 5,
    "hotword_target_model": "hey jarvis",
}


def load_voice_state(state_path: str | None = None) -> dict[str, Any]:
    path = Path(state_path) if state_path else DEFAULT_STATE_PATH
    if not path.exists():
        return dict(DEFAULT_STATE)

    data = json.loads(path.read_text(encoding="utf-8"))
    merged = dict(DEFAULT_STATE)
    merged.update(data)
    return merged


def save_voice_state(state: dict[str, Any], state_path: str | None = None) -> dict[str, Any]:
    path = Path(state_path) if state_path else DEFAULT_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = dict(DEFAULT_STATE)
    merged.update(state)

    path.write_text(
        json.dumps(merged, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "ok": True,
        "state_path": str(path),
        "keys_saved": sorted(merged.keys()),
    }


if __name__ == "__main__":
    raise SystemExit("voice_state.py is a module, not a standalone runner")
