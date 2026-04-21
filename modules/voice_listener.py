from __future__ import annotations

import subprocess
import wave
from pathlib import Path
from typing import Any, Generator


DEFAULT_DEVICE = "plughw:VX800,0"
DEFAULT_RATE = 16000
DEFAULT_CHANNELS = 1
DEFAULT_FORMAT = "S16_LE"
DEFAULT_SAMPLE_WIDTH = 2


def record_wav(
    output_path: str,
    *,
    duration: int = 4,
    device: str = DEFAULT_DEVICE,
    rate: int = DEFAULT_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_format: str = DEFAULT_FORMAT,
) -> dict[str, Any]:
    cmd = [
        "arecord",
        "-D", device,
        "-f", sample_format,
        "-r", str(rate),
        "-c", str(channels),
        "-d", str(duration),
        output_path,
    ]

    proc = subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        check=False,
    )

    return {
        "ok": proc.returncode == 0,
        "mode": "record_wav",
        "output_path": output_path,
        "device": device,
        "duration": duration,
        "rate": rate,
        "channels": channels,
        "format": sample_format,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "command": cmd,
    }


def build_arecord_stream_cmd(
    *,
    device: str = DEFAULT_DEVICE,
    rate: int = DEFAULT_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_format: str = DEFAULT_FORMAT,
) -> list[str]:
    return [
        "arecord",
        "-D", device,
        "-f", sample_format,
        "-r", str(rate),
        "-c", str(channels),
        "-t", "raw",
    ]


def frame_stream(
    *,
    device: str = DEFAULT_DEVICE,
    rate: int = DEFAULT_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_format: str = DEFAULT_FORMAT,
    frame_ms: int = 30,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> Generator[bytes, None, None]:
    if frame_ms <= 0:
        raise ValueError("frame_ms_must_be_positive")
    if channels <= 0:
        raise ValueError("channels_must_be_positive")
    if rate <= 0:
        raise ValueError("rate_must_be_positive")
    if sample_width <= 0:
        raise ValueError("sample_width_must_be_positive")

    bytes_per_frame = int(rate * frame_ms / 1000) * channels * sample_width
    if bytes_per_frame <= 0:
        raise ValueError("invalid_bytes_per_frame")

    cmd = build_arecord_stream_cmd(
        device=device,
        rate=rate,
        channels=channels,
        sample_format=sample_format,
    )

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    try:
        if proc.stdout is None:
            raise RuntimeError("arecord_stdout_unavailable")

        pending = b""
        while True:
            chunk = proc.stdout.read(bytes_per_frame)
            if not chunk:
                break
            pending += chunk
            while len(pending) >= bytes_per_frame:
                yield pending[:bytes_per_frame]
                pending = pending[bytes_per_frame:]
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)


def write_wav_from_pcm(
    output_path: str,
    pcm_bytes: bytes,
    *,
    rate: int = DEFAULT_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> dict[str, Any]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        wf.writeframes(pcm_bytes)

    frames = len(pcm_bytes) // max(1, channels * sample_width)
    duration_ms = int((frames / rate) * 1000) if rate > 0 else 0

    return {
        "ok": True,
        "output_path": str(path),
        "bytes_written": len(pcm_bytes),
        "frames": frames,
        "duration_ms": duration_ms,
        "rate": rate,
        "channels": channels,
        "sample_width": sample_width,
    }


def record_segment(
    output_path: str,
    pcm_frames: list[bytes],
    *,
    rate: int = DEFAULT_RATE,
    channels: int = DEFAULT_CHANNELS,
    sample_width: int = DEFAULT_SAMPLE_WIDTH,
) -> dict[str, Any]:
    pcm_bytes = b"".join(pcm_frames)
    result = write_wav_from_pcm(
        output_path,
        pcm_bytes,
        rate=rate,
        channels=channels,
        sample_width=sample_width,
    )
    result["mode"] = "record_segment"
    result["frame_count"] = len(pcm_frames)
    return result


if __name__ == "__main__":
    raise SystemExit("voice_listener.py is a module, not a standalone runner")
