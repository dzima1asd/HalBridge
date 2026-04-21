from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from modules.voice_listener import record_wav
from modules.voice_stt import transcribe_wav
from modules.voice_state import load_voice_state


DEFAULT_WAV_DIR = "/home/hal/HALbridge/tmp_voice"
DEFAULT_DAEMON_PATH = "/home/hal/HALbridge/voice_daemon.py"


def run_voice_daemon(text: str, daemon_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, daemon_path, text],
        text=True,
        capture_output=True,
        check=False,
    )


def make_wav_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{DEFAULT_WAV_DIR}/voice_capture_{ts}.wav"


def main() -> int:
    state = load_voice_state()
    duration = int(state.get("default_record_seconds", 4))
    if len(sys.argv) > 1:
        duration = int(sys.argv[1])

    listener_device = str(state.get("listener_device", "plughw:VX800,0"))
    stt_model_path = str(state.get("stt_model_path", "/home/hal/models/vosk/vosk-model-small-pl-0.22"))

    wav_path = make_wav_path()
    Path(DEFAULT_WAV_DIR).mkdir(parents=True, exist_ok=True)

    rec = record_wav(wav_path, duration=duration, device=listener_device)

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
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1

    try:
        stt = transcribe_wav(wav_path, model_path=stt_model_path)
    except Exception as e:
        result["ok"] = False
        result["stt"] = {
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2

    result["stt"] = stt
    text = (stt.get("text") or "").strip()

    if not text:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    proc = run_voice_daemon(text, DEFAULT_DAEMON_PATH)
    result["daemon_returncode"] = proc.returncode
    result["daemon_stdout"] = proc.stdout
    result["daemon_stderr"] = proc.stderr

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
