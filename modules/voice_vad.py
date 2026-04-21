from __future__ import annotations

import audioop
from dataclasses import dataclass
from typing import Any


VALID_RATES = {8000, 16000, 32000, 48000}
VALID_FRAME_MS = {10, 20, 30}
DEFAULT_RATE = 16000
DEFAULT_FRAME_MS = 30


@dataclass
class VADDecision:
    state: str
    is_speech: bool
    confidence: float
    source: str
    frame_ms: int
    rate: int
    rms: int
    threshold: int
    debug: dict[str, Any]


class SimpleEnergyVAD:
    def __init__(self, threshold: int = 450) -> None:
        self.threshold = int(threshold)

    def is_speech(self, pcm_bytes: bytes, sample_rate: int) -> tuple[bool, int]:
        rms = audioop.rms(pcm_bytes, 2) if pcm_bytes else 0
        return rms >= self.threshold, rms


class VoiceVAD:
    def __init__(
        self,
        *,
        aggressiveness: int = 2,
        sample_rate: int = DEFAULT_RATE,
        frame_ms: int = DEFAULT_FRAME_MS,
        start_frames: int = 2,
        end_frames: int = 6,
        energy_threshold: int = 450,
    ) -> None:
        self.sample_rate = int(sample_rate)
        self.frame_ms = int(frame_ms)
        self.start_frames = max(1, int(start_frames))
        self.end_frames = max(1, int(end_frames))
        self.energy_threshold = int(energy_threshold)

        if self.sample_rate not in VALID_RATES:
            raise ValueError(f"unsupported_sample_rate:{self.sample_rate}")
        if self.frame_ms not in VALID_FRAME_MS:
            raise ValueError(f"unsupported_frame_ms:{self.frame_ms}")

        self.samples_per_frame = int(self.sample_rate * self.frame_ms / 1000)
        self.bytes_per_frame = self.samples_per_frame * 2

        self._speech_run = 0
        self._silence_run = 0
        self._in_speech = False

        self.backend_name = "energy"
        self._backend = None

        try:
            import webrtcvad  # type: ignore
            self._backend = webrtcvad.Vad(max(0, min(3, int(aggressiveness))))
            self.backend_name = "webrtcvad"
        except Exception:
            self._backend = SimpleEnergyVAD(threshold=self.energy_threshold)
            self.backend_name = "energy"

    def reset(self) -> None:
        self._speech_run = 0
        self._silence_run = 0
        self._in_speech = False

    def expected_num_bytes(self) -> int:
        return self.bytes_per_frame

    def analyze_frame(self, pcm_bytes: bytes) -> VADDecision:
        if len(pcm_bytes) != self.bytes_per_frame:
            raise ValueError(
                f"invalid_frame_size:{len(pcm_bytes)} expected:{self.bytes_per_frame}"
            )

        if self.backend_name == "webrtcvad":
            assert self._backend is not None
            is_speech = bool(self._backend.is_speech(pcm_bytes, self.sample_rate))
            rms = audioop.rms(pcm_bytes, 2) if pcm_bytes else 0
            confidence = 0.9 if is_speech else 0.1
        else:
            assert self._backend is not None
            is_speech, rms = self._backend.is_speech(pcm_bytes, self.sample_rate)
            confidence = min(1.0, rms / max(1, self.energy_threshold * 2))

        if is_speech:
            self._speech_run += 1
            self._silence_run = 0
        else:
            self._silence_run += 1
            self._speech_run = 0

        if not self._in_speech:
            if is_speech and self._speech_run >= self.start_frames:
                self._in_speech = True
                state = "speech_started"
            else:
                state = "silence"
        else:
            if not is_speech and self._silence_run >= self.end_frames:
                self._in_speech = False
                state = "speech_ended"
            else:
                state = "speech_ongoing"

        return VADDecision(
            state=state,
            is_speech=is_speech,
            confidence=round(confidence, 3),
            source=self.backend_name,
            frame_ms=self.frame_ms,
            rate=self.sample_rate,
            rms=rms,
            threshold=self.energy_threshold,
            debug={
                "speech_run": self._speech_run,
                "silence_run": self._silence_run,
                "in_speech": self._in_speech,
            },
        )

    def analyze_frame_dict(self, pcm_bytes: bytes) -> dict[str, Any]:
        d = self.analyze_frame(pcm_bytes)
        return {
            "state": d.state,
            "is_speech": d.is_speech,
            "confidence": d.confidence,
            "source": d.source,
            "frame_ms": d.frame_ms,
            "rate": d.rate,
            "rms": d.rms,
            "threshold": d.threshold,
            "debug": d.debug,
        }


if __name__ == "__main__":
    raise SystemExit("voice_vad.py is a module, not a standalone runner")
