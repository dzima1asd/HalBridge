from __future__ import annotations

import json
import subprocess
import sys

from modules.voice_stt import transcribe_wav


DEFAULT_DAEMON_PATH = "/home/hal/HALbridge/voice_daemon.py"


def run_voice_daemon(text: str, daemon_path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, daemon_path, text],
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    if len(sys.argv) < 2:
        print(json.dumps({
            "ok": False,
            "stage": "args",
            "error": "usage: python3 voice_stt_file_runner.py /path/to/file.wav [model_path]",
        }, ensure_ascii=False, indent=2))
        return 1

    wav_path = sys.argv[1]
    model_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        if model_path:
            stt = transcribe_wav(wav_path, model_path=model_path)
        else:
            stt = transcribe_wav(wav_path)
    except Exception as e:
        print(json.dumps({
            "ok": False,
            "stage": "stt",
            "wav_path": wav_path,
            "model_path": model_path,
            "error": f"{type(e).__name__}: {e}",
        }, ensure_ascii=False, indent=2))
        return 2

    text = (stt.get("text") or "").strip()

    result = {
        "ok": True,
        "wav_path": wav_path,
        "model_path": stt.get("model_path"),
        "stt": stt,
        "daemon_returncode": None,
        "daemon_stdout": None,
        "daemon_stderr": None,
    }

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
