# LEGACY_RUNNER: retained for old test flow; new development should use voice_runtime.py
from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from modules.voice_listener import record_wav
from modules.voice_stt import transcribe_wav
from modules.voice_state import load_voice_state


DEFAULT_WAV_DIR = "/home/hal/HALbridge/tmp_voice/live"
DEFAULT_DAEMON_PATH = "/home/hal/HALbridge/voice_daemon.py"


def make_wav_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{DEFAULT_WAV_DIR}/live_{ts}.wav"


def run_voice_daemon(text: str, daemon_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, daemon_path, text],
        text=True,
        capture_output=True,
        check=False,
    )


def one_cycle() -> dict:
    state = load_voice_state()
    duration = int(state.get("default_record_seconds", 4))
    device = str(state.get("listener_device", "plughw:VX800,0"))
    model_path = str(state.get("stt_model_path", "/home/hal/models/vosk/vosk-model-small-pl-0.22"))

    Path(DEFAULT_WAV_DIR).mkdir(parents=True, exist_ok=True)
    wav_path = make_wav_path()

    rec = record_wav(wav_path, duration=duration, device=device)

    result = {
        "ok": True,
        "record": rec,
        "stt": None,
        "daemon_returncode": None,
        "daemon_stdout": None,
        "daemon_stderr": None,
    }

    if not rec.get("ok"):
        result["ok"] = False
        result["stage"] = "record"
        return result

    try:
        stt = transcribe_wav(wav_path, model_path=model_path)
    except Exception as e:
        result["ok"] = False
        result["stage"] = "stt"
        result["stt"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }
        return result

    result["stt"] = stt
    text = (stt.get("text") or "").strip()

    if not text:
        result["stage"] = "empty_text"
        return result

    proc = run_voice_daemon(text, DEFAULT_DAEMON_PATH)
    result["daemon_returncode"] = proc.returncode
    result["daemon_stdout"] = proc.stdout
    result["daemon_stderr"] = proc.stderr
    result["stage"] = "done"
    return result


def main() -> int:
    print("VOICE_LIVE_V1_START")
    print("Ctrl+C aby zakończyć")
    try:
        while True:
            result = one_cycle()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("-" * 60)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("VOICE_LIVE_V1_STOP")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
