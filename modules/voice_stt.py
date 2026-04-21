from __future__ import annotations

import json
import time
import wave
from pathlib import Path
from typing import Any

try:
    from vosk import KaldiRecognizer, Model
    VOSK_AVAILABLE = True
    VOSK_IMPORT_ERROR = None
except Exception as e:
    KaldiRecognizer = None
    Model = None
    VOSK_AVAILABLE = False
    VOSK_IMPORT_ERROR = f"{type(e).__name__}: {e}"


DEFAULT_MODEL_PATH = "/home/hal/models/vosk/vosk-model-small-pl-0.22"
MODEL_CACHE: dict[str, Any] = {}


def get_model(model_path: str = DEFAULT_MODEL_PATH):
    if not VOSK_AVAILABLE:
        raise RuntimeError(f"vosk_unavailable:{VOSK_IMPORT_ERROR}")

    path = str(Path(model_path).expanduser())
    model = MODEL_CACHE.get(path)
    if model is None:
        model = Model(path)
        MODEL_CACHE[path] = model
    return model


def transcribe_wav(wav_path: str, model_path: str = DEFAULT_MODEL_PATH) -> dict[str, Any]:
    started_at = time.perf_counter()

    if not VOSK_AVAILABLE:
        return {
            "ok": False,
            "wav_path": wav_path,
            "model_path": str(Path(model_path).expanduser()),
            "text": "",
            "transcript": "",
            "duration_ms": 0,
            "latency_ms": int((time.perf_counter() - started_at) * 1000),
            "empty_result": True,
            "error": "vosk_unavailable",
            "error_detail": VOSK_IMPORT_ERROR,
        }

    wf = wave.open(wav_path, "rb")
    try:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        rate = wf.getframerate()
        total_frames = wf.getnframes()
        duration_ms = int((total_frames / rate) * 1000) if rate > 0 else 0

        if channels != 1:
            raise ValueError(f"unsupported_channels:{channels}")
        if sample_width != 2:
            raise ValueError(f"unsupported_sample_width:{sample_width}")
        if rate not in (8000, 16000, 32000, 44100, 48000):
            raise ValueError(f"unsupported_rate:{rate}")

        rec = KaldiRecognizer(get_model(model_path), rate)
        rec.SetWords(True)

        while True:
            data = wf.readframes(4000)
            if not data:
                break
            rec.AcceptWaveform(data)

        final_raw = rec.FinalResult()
        final_obj = json.loads(final_raw)

        transcript = (final_obj.get("text") or "").strip()
        latency_ms = int((time.perf_counter() - started_at) * 1000)

        return {
            "ok": True,
            "wav_path": wav_path,
            "model_path": str(Path(model_path).expanduser()),
            "channels": channels,
            "sample_width": sample_width,
            "rate": rate,
            "frames": total_frames,
            "duration_ms": duration_ms,
            "latency_ms": latency_ms,
            "text": transcript,
            "transcript": transcript,
            "empty_result": not bool(transcript),
            "raw_result": final_obj,
            "vosk_available": True,
        }
    finally:
        wf.close()


if __name__ == "__main__":
    raise SystemExit("voice_stt.py is a module, not a standalone runner")
