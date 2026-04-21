#!/usr/bin/env python3
import json
import shutil
import subprocess
import sys
from pathlib import Path

from modules.voice_stt_hybrid import transcribe_wav_hybrid

WHISPER_BIN = Path("/home/hal/tools/whisper.cpp/build/bin/whisper-cli")
WHISPER_MODEL = Path("/home/hal/tools/whisper.cpp/models/ggml-base.bin")

def run_hybrid(wav_path: str) -> dict:
    state = {
        "hybrid_stt_enabled": True,
        "hybrid_stt_youtube_enabled": True,
        "stt_model_path": "/home/hal/models/vosk/vosk-model-small-pl-0.22",
        "stt_model_path_en": "/home/hal/models/vosk/vosk-model-small-en-us-0.15",
    }
    res = transcribe_wav_hybrid(wav_path, state=state, model_path_pl=state["stt_model_path"])
    return {
        "ok": res.get("ok"),
        "transcript": res.get("transcript"),
        "transcript_pl": res.get("transcript_pl"),
        "transcript_en": res.get("transcript_en"),
        "transcript_en_tail": res.get("transcript_en_tail"),
        "query_final": res.get("query_final"),
        "query_source": res.get("query_source"),
        "query_scores": res.get("query_scores"),
        "hybrid_reason": res.get("hybrid_reason"),
        "error": res.get("error"),
    }

def run_whisper(wav_path: str) -> dict:
    if not WHISPER_BIN.exists():
        return {"ok": False, "error": f"missing_bin:{WHISPER_BIN}"}
    if not WHISPER_MODEL.exists():
        return {"ok": False, "error": f"missing_model:{WHISPER_MODEL}"}

    cmd = [
        str(WHISPER_BIN),
        "-m", str(WHISPER_MODEL),
        "-l", "auto",
        "-f", wav_path,
        "-nt",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True, check=False)
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    lines = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
    transcript_lines = []
    for ln in lines:
        if ln.startswith("["):
            if "]" in ln:
                tail = ln.split("]", 1)[1].strip()
                if tail:
                    transcript_lines.append(tail)
        elif not ln.startswith("whisper_") and not ln.startswith("system_info:") and not ln.startswith("main:"):
            transcript_lines.append(ln)
    transcript = " ".join(transcript_lines).strip()
    return {
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "transcript": transcript,
        "stdout": stdout,
        "stderr": stderr,
    }

def main():
    if len(sys.argv) != 2:
        print("Użycie: python3 stt_compare.py /ścieżka/do/pliku.wav")
        raise SystemExit(2)

    wav = str(Path(sys.argv[1]).expanduser().resolve())
    result = {
        "wav": wav,
        "hybrid": run_hybrid(wav),
        "whisper": run_whisper(wav),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
