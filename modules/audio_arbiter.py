from __future__ import annotations

import os
import signal
from typing import Any

from modules.voice_runtime_state import load_runtime_status, save_runtime_status
from modules.voice_logger import log_voice_event
from modules.voice_tts import speak_text
from modules.audio_runtime import handle_audio_runtime
from modules.hardware_bridge import HardwareBridge


def block_listening(*, reason: str = "tts") -> dict[str, Any]:
    status = load_runtime_status()
    status["listening_blocked"] = True
    status["block_reason"] = reason
    return save_runtime_status(status)


def unblock_listening() -> dict[str, Any]:
    status = load_runtime_status()
    status["listening_blocked"] = False
    status["block_reason"] = None
    return save_runtime_status(status)



def stop_active_tts_session(*, source: str = "voice_runtime_stopword") -> dict[str, Any]:
    status = load_runtime_status()
    pid = status.get("tts_player_pid")
    player_name = status.get("tts_player_name")
    session_id = status.get("tts_session_id")

    stopped = False
    kill_method = None
    error = None

    if pid:
        try:
            os.killpg(pid, signal.SIGTERM)
            stopped = True
            kill_method = "killpg_sigterm"
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
                stopped = True
                kill_method = "kill_sigterm"
            except Exception as e:
                error = f"{type(e).__name__}: {e}"

    end_info = end_tts(error="tts_stopped_by_voice")

    log_voice_event(
        "tts_stopped",
        source="audio_arbiter",
        current_state="idle",
        action_taken="stop_tts",
        error=error,
        data={
            "stopped": stopped,
            "kill_method": kill_method,
            "player_name": player_name,
            "player_pid": pid,
            "tts_session_id": session_id,
            "source": source,
        },
    )

    return {
        "ok": True,
        "stopped": stopped,
        "kill_method": kill_method,
        "player_name": player_name,
        "player_pid": pid,
        "tts_session_id": session_id,
        "end": end_info,
        "error": error,
    }


def prepare_tts_output(mode: str = "current") -> dict[str, Any]:
    low = (mode or "current").strip().lower()

    if low == "current":
        return {
            "ok": True,
            "changed": False,
            "mode": "current",
            "message": "audio_output_unchanged",
        }

    if low == "jbl":
        handled, message = handle_audio_runtime("jbl on")
        return {
            "ok": bool(handled),
            "changed": bool(handled),
            "mode": "jbl",
            "message": message,
        }

    if low == "default":
        handled, message = handle_audio_runtime("jbl off")
        return {
            "ok": bool(handled),
            "changed": bool(handled),
            "mode": "default",
            "message": message,
        }

    return {
        "ok": False,
        "changed": False,
        "mode": low,
        "message": "unknown_output_mode",
    }



_HW_BRIDGE = None


def _get_hw_bridge() -> HardwareBridge | None:
    global _HW_BRIDGE
    if _HW_BRIDGE is None:
        try:
            _HW_BRIDGE = HardwareBridge()
        except Exception:
            _HW_BRIDGE = None
    return _HW_BRIDGE


def ensure_default_speaker_ready() -> dict[str, Any]:
    status = load_runtime_status()

    bridge = _get_hw_bridge()
    if bridge is None:
        return {
            "ok": False,
            "changed": False,
            "message": "speaker_bridge_unavailable",
        }

    try:
        reply = bridge.execute("wlacz glosnik")
    except Exception as e:
        return {
            "ok": False,
            "changed": False,
            "message": f"speaker_auto_on_error:{type(e).__name__}: {e}",
        }

    status["speaker_auto_on_done"] = True
    save_runtime_status(status)

    return {
        "ok": True,
        "changed": True,
        "message": reply or "speaker_auto_on_triggered",
    }


def begin_tts(*, source: str = "voice_tts") -> dict[str, Any]:
    status = load_runtime_status()
    status["current_state"] = "speaking"
    status["last_error"] = None
    status["tts_active"] = True
    status["tts_source"] = source
    status["tts_player_pid"] = None
    status["tts_player_name"] = None
    status["tts_session_id"] = str(int(__import__("time").time() * 1000))
    status["tts_interruptible"] = True
    status["listening_blocked"] = True
    status["block_reason"] = "tts"
    result = save_runtime_status(status)
    log_voice_event(
        "tts_started",
        source="audio_arbiter",
        current_state="speaking",
        data={"tts_source": source},
    )
    return result


def end_tts(*, error: str | None = None) -> dict[str, Any]:
    status = load_runtime_status()
    status["current_state"] = "idle"
    status["tts_active"] = False
    status["tts_source"] = None
    status["tts_player_pid"] = None
    status["tts_player_name"] = None
    status["tts_session_id"] = None
    status["tts_interruptible"] = False
    status["listening_blocked"] = False
    status["block_reason"] = None
    status["last_error"] = error
    result = save_runtime_status(status)
    log_voice_event(
        "tts_finished" if not error else "error",
        source="audio_arbiter",
        current_state="idle",
        error=error,
        data={"tts_source": None},
    )
    return result


def speak_with_arbiter(
    text: str,
    *,
    preferred_provider: str = "piper",
    play_audio: bool = True,
    source: str = "voice_tts",
    output_mode: str = "current",
    tts_fx_mode: str = "standard",
) -> dict[str, Any]:
    speaker_prepare = ensure_default_speaker_ready() if play_audio else {
        "ok": True,
        "changed": False,
        "message": "speaker_prepare_skipped",
    }
    output_prepare = prepare_tts_output(output_mode)
    begin_info = begin_tts(source=source)

    result = speak_text(
        text,
        preferred_provider=preferred_provider,
        play_audio=play_audio,
        tts_fx_mode=tts_fx_mode,
    )

    try:
        status = load_runtime_status()
        play_info = result.get("play_result") or {}
        status["tts_player_pid"] = play_info.get("player_pid")
        status["tts_player_name"] = play_info.get("player")
        save_runtime_status(status)
    except Exception:
        pass

    end_info = end_tts(error=result.get("error"))

    log_voice_event(
        "tts_result",
        source="audio_arbiter",
        current_state="idle",
        action_taken="tts_playback",
        reply_text=text,
        error=result.get("error"),
        data={
            "provider": result.get("provider"),
            "played": result.get("played"),
            "latency_ms": result.get("latency_ms"),
            "ok": result.get("ok"),
            "tts_fx_mode": result.get("tts_fx_mode"),
            "final_wav_path": result.get("final_wav_path"),
        },
    )

    return {
        "ok": result.get("ok", False),
        "speaker_prepare": speaker_prepare,
        "output_prepare": output_prepare,
        "begin": begin_info,
        "tts": result,
        "end": end_info,
        "error": result.get("error"),
    }


if __name__ == "__main__":
    raise SystemExit("audio_arbiter.py is a module, not a standalone runner")
