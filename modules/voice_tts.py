from __future__ import annotations

import os
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_TTS_DIR = Path.home() / "HALbridge/tmp_voice/tts"
DEFAULT_PIPER_MODEL = str(Path.home() / "models/piper/pl_PL-gosia-medium.onnx")
DEFAULT_PIPER_CONFIG = str(Path.home() / "models/piper/pl_PL-gosia-medium.onnx.json")
DEFAULT_ESPEAK_VOICE = "pl"


DEFAULT_TTS_FX_MODE = "standard"


def make_tts_fx_wav_path(prefix: str = "tts_fx") -> str:
    DEFAULT_TTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(DEFAULT_TTS_DIR / f"{prefix}_{ts}.wav")


def apply_tts_fx(
    wav_path: str,
    *,
    fx_mode: str = DEFAULT_TTS_FX_MODE,
    out_path: str | None = None,
) -> dict[str, Any]:
    src = Path(wav_path)
    mode = (fx_mode or DEFAULT_TTS_FX_MODE).strip().lower()

    if not src.exists():
        return {
            "ok": False,
            "fx_mode": mode,
            "input_wav_path": wav_path,
            "output_wav_path": out_path,
            "error": f"missing_input_wav:{wav_path}",
        }

    if mode in ("", "standard", "normal", "off", "none"):
        return {
            "ok": True,
            "fx_mode": "standard",
            "input_wav_path": wav_path,
            "output_wav_path": wav_path,
            "applied": False,
            "error": None,
        }

    if mode not in ("dark", "cyborg"):
        return {
            "ok": False,
            "fx_mode": mode,
            "input_wav_path": wav_path,
            "output_wav_path": out_path,
            "error": f"unsupported_tts_fx_mode:{mode}",
        }

    if not shutil.which("ffmpeg"):
        return {
            "ok": False,
            "fx_mode": mode,
            "input_wav_path": wav_path,
            "output_wav_path": out_path,
            "error": "ffmpeg_not_found",
        }

    dst = out_path or make_tts_fx_wav_path(f"tts_{mode}")

    if mode == "dark":
        af = ",".join([
            "asetrate=22050*0.86",
            "aresample=22050",
            "highpass=f=180",
            "lowpass=f=2400",
            "chorus=0.5:0.9:40:0.35:0.25:2",
            "tremolo=f=24:d=0.55",
            "aecho=0.7:0.5:18:0.22",
            "equalizer=f=900:t=q:w=1.0:g=5",
            "equalizer=f=1800:t=q:w=0.8:g=6",
            "equalizer=f=2600:t=q:w=0.7:g=-4",
            "volume=1.8",
        ])
    else:
        af = ",".join([
            "asetrate=22050*0.93",
            "aresample=22050",
            "highpass=f=180",
            "lowpass=f=4800",
            "chorus=0.70:0.90:5:0.35:0.20:0.40",
            "tremolo=f=32:d=0.22",
            "equalizer=f=500:t=q:w=1.0:g=-4",
            "equalizer=f=1450:t=q:w=0.9:g=4",
            "equalizer=f=2300:t=q:w=0.6:g=10",
            "equalizer=f=3200:t=q:w=0.7:g=8",
            "equalizer=f=4100:t=q:w=0.8:g=-3",
            "volume=1.15",
        ])

    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(src),
        "-af", af,
        "-ar", "22050",
        "-ac", "1",
        dst,
    ]

    rc, out, err = _run(cmd)
    ok = rc == 0 and Path(dst).exists()

    return {
        "ok": ok,
        "fx_mode": mode,
        "input_wav_path": wav_path,
        "output_wav_path": dst,
        "applied": ok,
        "returncode": rc,
        "stdout": out,
        "stderr": err,
        "error": None if ok else ((err or "").strip() or "tts_fx_failed"),
    }


def make_tts_wav_path(prefix: str = "tts") -> str:
    DEFAULT_TTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return str(DEFAULT_TTS_DIR / f"{prefix}_{ts}.wav")


def _run(cmd: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def synthesize_with_piper(
    text: str,
    *,
    wav_path: str,
    model_path: str = DEFAULT_PIPER_MODEL,
    config_path: str = DEFAULT_PIPER_CONFIG,
) -> dict[str, Any]:
    piper_bin = shutil.which("piper") or str(Path.home() / "bin/piper")
    if not Path(piper_bin).exists():
        return {
            "ok": False,
            "provider": "piper",
            "wav_path": wav_path,
            "error": "piper_not_found",
        }

    if not Path(model_path).exists():
        return {
            "ok": False,
            "provider": "piper",
            "wav_path": wav_path,
            "error": f"missing_model:{model_path}",
        }

    cmd = [
        piper_bin,
        "--model", model_path,
        "--output_file", wav_path,
    ]

    if Path(config_path).exists():
        cmd.extend(["--config", config_path])

    proc = subprocess.run(
        cmd,
        input=text,
        text=True,
        capture_output=True,
        check=False,
    )

    ok = proc.returncode == 0 and Path(wav_path).exists()

    return {
        "ok": ok,
        "provider": "piper",
        "wav_path": wav_path,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "error": None if ok else (proc.stderr.strip() or "piper_failed"),
    }


def synthesize_with_espeak(
    text: str,
    *,
    wav_path: str,
    voice: str = DEFAULT_ESPEAK_VOICE,
) -> dict[str, Any]:
    if not shutil.which("espeak-ng"):
        return {
            "ok": False,
            "provider": "espeak-ng",
            "wav_path": wav_path,
            "error": "espeak_ng_not_found",
        }

    cmd = [
        "espeak-ng",
        "-v", voice,
        "-w", wav_path,
        text,
    ]

    rc, out, err = _run(cmd)
    ok = rc == 0 and Path(wav_path).exists()

    return {
        "ok": ok,
        "provider": "espeak-ng",
        "wav_path": wav_path,
        "returncode": rc,
        "stdout": out,
        "stderr": err,
        "error": None if ok else (err.strip() or "espeak_ng_failed"),
    }


def _play_wav_with_cmd(
    cmd: list[str],
    player_name: str,
    wav_path: str,
    *,
    on_start=None,
) -> dict[str, Any]:
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        if on_start is not None:
            try:
                on_start(proc.pid, player_name, wav_path)
            except Exception:
                pass
    except Exception as e:
        return {
            "ok": False,
            "player": player_name,
            "wav_path": wav_path,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "player_pid": None,
            "error": f"spawn_failed:{type(e).__name__}: {e}",
        }

    try:
        out, err = proc.communicate()
    except Exception:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        raise

    rc = proc.returncode
    return {
        "ok": rc == 0,
        "player": player_name,
        "wav_path": wav_path,
        "returncode": rc,
        "stdout": out,
        "stderr": err,
        "player_pid": proc.pid,
        "error": None if rc == 0 else ((err or "").strip() or f"{player_name}_failed"),
    }


def play_wav(wav_path: str, *, on_start=None) -> dict[str, Any]:
    if shutil.which("paplay"):
        return _play_wav_with_cmd(["paplay", wav_path], "paplay", wav_path, on_start=on_start)

    if shutil.which("aplay"):
        return _play_wav_with_cmd(["aplay", wav_path], "aplay", wav_path, on_start=on_start)

    return {
        "ok": False,
        "player": None,
        "wav_path": wav_path,
        "player_pid": None,
        "error": "no_audio_player_found",
    }


def synthesize_tts(
    text: str,
    *,
    wav_path: str | None = None,
    preferred_provider: str = "piper",
) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {
            "ok": False,
            "provider": None,
            "wav_path": None,
            "error": "empty_text",
        }

    out_path = wav_path or make_tts_wav_path()

    providers = ["piper", "espeak-ng"]
    if preferred_provider == "espeak-ng":
        providers = ["espeak-ng", "piper"]

    attempts: list[dict[str, Any]] = []

    for provider in providers:
        if provider == "piper":
            res = synthesize_with_piper(raw, wav_path=out_path)
        else:
            res = synthesize_with_espeak(raw, wav_path=out_path)

        attempts.append(res)
        if res.get("ok"):
            return {
                "ok": True,
                "provider": res.get("provider"),
                "wav_path": out_path,
                "attempts": attempts,
                "error": None,
            }

    return {
        "ok": False,
        "provider": None,
        "wav_path": out_path,
        "attempts": attempts,
        "error": "all_tts_providers_failed",
    }


def speak_text(
    text: str,
    *,
    wav_path: str | None = None,
    preferred_provider: str = "piper",
    play_audio: bool = True,
    on_playback_start=None,
    tts_fx_mode: str = DEFAULT_TTS_FX_MODE,
) -> dict[str, Any]:
    t0 = time.perf_counter()
    synth = synthesize_tts(
        text,
        wav_path=wav_path,
        preferred_provider=preferred_provider,
    )

    if not synth.get("ok"):
        synth["played"] = False
        synth["latency_ms"] = int((time.perf_counter() - t0) * 1000)
        return synth

    fx_result = apply_tts_fx(synth["wav_path"], fx_mode=tts_fx_mode)
    final_wav_path = fx_result.get("output_wav_path") or synth["wav_path"]

    play_result = {"ok": True, "player": None, "wav_path": final_wav_path, "error": None}
    played = False

    if not fx_result.get("ok"):
        return {
            "ok": False,
            "provider": synth.get("provider"),
            "wav_path": synth.get("wav_path"),
            "fx_result": fx_result,
            "played": False,
            "play_result": play_result,
            "attempts": synth.get("attempts", []),
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "error": fx_result.get("error") or synth.get("error"),
        }

    if play_audio:
        play_result = play_wav(final_wav_path, on_start=on_playback_start)
        played = bool(play_result.get("ok"))

    return {
        "ok": bool(synth.get("ok")) and bool(fx_result.get("ok")) and (played if play_audio else True),
        "provider": synth.get("provider"),
        "wav_path": synth.get("wav_path"),
        "final_wav_path": final_wav_path,
        "tts_fx_mode": fx_result.get("fx_mode"),
        "fx_result": fx_result,
        "played": played if play_audio else False,
        "play_result": play_result,
        "attempts": synth.get("attempts", []),
        "latency_ms": int((time.perf_counter() - t0) * 1000),
        "error": None if (synth.get("ok") and fx_result.get("ok") and (played if play_audio else True)) else (
            play_result.get("error") or fx_result.get("error") or synth.get("error")
        ),
    }


if __name__ == "__main__":
    raise SystemExit("voice_tts.py is a module, not a standalone runner")
