from __future__ import annotations

import json
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from modules.voice_listener import frame_stream, record_segment
from modules.voice_logger import log_voice_event
from modules.audio_arbiter import speak_with_arbiter, stop_active_tts_session
from modules.voice_runtime_state import load_runtime_status, mark_runtime_error, mark_runtime_state
from modules.voice_state import load_voice_state
from modules.voice_stt_hybrid import transcribe_wav_hybrid
from modules.voice_session import end_voice_session, is_session_active, start_voice_session, touch_voice_session
from modules.voice_vad import VoiceVAD
from modules.voice_hotword import detect_hotword, hotword_backend_status


DEFAULT_WAV_DIR = "/home/hal/HALbridge/tmp_voice/runtime"
DEFAULT_DAEMON_PATH = "/home/hal/HALbridge/voice_daemon.py"


def make_wav_path() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{DEFAULT_WAV_DIR}/runtime_{ts}.wav"


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)



def is_tts_stop_command(text: str) -> bool:
    low = (text or "").strip().lower()
    low = (
        low.replace("ą", "a")
        .replace("ć", "c")
        .replace("ę", "e")
        .replace("ł", "l")
        .replace("ń", "n")
        .replace("ó", "o")
        .replace("ś", "s")
        .replace("ź", "z")
        .replace("ż", "z")
    )

    cleaned = []
    for ch in low:
        cleaned.append(ch if (ch.isalnum() or ch.isspace()) else " ")
    low = " ".join("".join(cleaned).split())

    tokens = set(low.split())

    single_words = {
        "stop",
        "cisza",
        "cicho",
        "dosc",
        "starczy",
        "wystarczy",
    }

    if any(word in tokens for word in single_words):
        return True

    phrases = (
        "nie gadaj",
        "nie gadac",
        "nie gada",
    )
    if any(phrase in low for phrase in phrases):
        return True

    return False


def cleanup_expired_session(runtime_status: dict[str, Any]) -> dict[str, Any]:
    status = dict(runtime_status)
    session = dict(status.get("session") or {})

    if session.get("active") and not is_session_active(session):
        session = end_voice_session(session)
        status["session"] = session
        log_voice_event(
            "session_expired",
            source="voice_runtime",
            current_state="idle",
            route=session.get("last_route"),
            data={"last_wake_word": session.get("last_wake_word")},
        )
        return status

    status["session"] = session
    return status


def update_session_after_daemon(
    runtime_status: dict[str, Any],
    *,
    daemon_route: str | None,
    daemon_action: str | None,
    daemon_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = dict(runtime_status)
    session = dict(status.get("session") or {})
    route = (daemon_route or "").strip().lower()
    action = (daemon_action or "").strip().lower()

    daemon_data = daemon_data or {}
    wake_result = daemon_data.get("wake_result") or {}
    wake_detected = bool(wake_result.get("wake_detected"))
    wake_word = wake_result.get("wake_word")

    should_start_or_extend = False

    if wake_detected:
        should_start_or_extend = True
    elif route in {"conversation", "smart_query"} or action == "reroute_to_agent":
        should_start_or_extend = True
    elif session.get("active") and route:
        should_start_or_extend = True

    if should_start_or_extend:
        if session.get("active"):
            session = touch_voice_session(session, timeout_seconds=20, route=route or None)
            if wake_word:
                session["last_wake_word"] = wake_word
            log_voice_event(
                "session_touched",
                source="voice_runtime",
                current_state="idle",
                route=route or None,
                data={
                    "wake_word": wake_word,
                    "turn_count": session.get("turn_count"),
                    "expires_at": session.get("expires_at"),
                },
            )
        else:
            session = start_voice_session(
                timeout_seconds=20,
                wake_word=wake_word,
                route=route or None,
            )
            log_voice_event(
                "session_started",
                source="voice_runtime",
                current_state="idle",
                route=route or None,
                data={
                    "wake_word": wake_word,
                    "expires_at": session.get("expires_at"),
                },
            )

    status["session"] = session
    return status


class VoiceRuntime:
    def __init__(self, state: dict[str, Any] | None = None) -> None:
        self.state = state or load_voice_state()

        self.device = str(self.state.get("listener_device", "plughw:VX800,0"))
        self.model_path = str(
            self.state.get(
                "stt_model_path",
                "/home/hal/models/vosk/vosk-model-small-pl-0.22",
            )
        )

        self.sample_rate = safe_int(self.state.get("listener_rate", 16000), 16000)
        self.channels = safe_int(self.state.get("listener_channels", 1), 1)
        self.sample_width = safe_int(self.state.get("listener_sample_width", 2), 2)
        self.frame_ms = safe_int(self.state.get("vad_frame_ms", 30), 30)

        self.vad_aggressiveness = safe_int(self.state.get("vad_aggressiveness", 2), 2)
        self.vad_start_frames = safe_int(self.state.get("speech_start_frames", 2), 2)

        speech_end_silence_ms = safe_int(self.state.get("speech_end_silence_ms", 0), 0)
        if speech_end_silence_ms > 0:
            self.vad_end_frames = max(1, int(round(speech_end_silence_ms / max(1, self.frame_ms))))
        else:
            self.vad_end_frames = safe_int(self.state.get("speech_end_frames", 6), 6)

        self.energy_threshold = safe_int(self.state.get("vad_energy_threshold", 450), 450)

        self.max_segment_seconds = safe_int(self.state.get("max_segment_seconds", 8), 8)
        self.max_idle_seconds = safe_int(self.state.get("max_idle_seconds", 10), 10)
        self.pre_roll_frames = safe_int(self.state.get("pre_roll_frames", 5), 5)
        self.cooldown_ms = safe_int(self.state.get("cooldown_ms", 800), 800)

        self.hotword_enabled = bool(self.state.get("hotword_enabled", False))
        self.hotword_backend = str(self.state.get("hotword_backend", "openwakeword"))
        self.hotword_threshold = float(self.state.get("hotword_threshold", 0.5))
        self.hotword_gate_frames = safe_int(self.state.get("hotword_gate_frames", 5), 5)
        self.hotword_target_model = str(self.state.get("hotword_target_model", "hey jarvis"))

        self.vad = VoiceVAD(
            aggressiveness=self.vad_aggressiveness,
            sample_rate=self.sample_rate,
            frame_ms=self.frame_ms,
            start_frames=self.vad_start_frames,
            end_frames=self.vad_end_frames,
            energy_threshold=self.energy_threshold,
        )

    def run_voice_daemon(self, text: str, daemon_path: str = DEFAULT_DAEMON_PATH) -> dict[str, Any]:
        proc = subprocess.run(
            [sys.executable, daemon_path, text],
            text=True,
            capture_output=True,
            check=False,
        )

        parsed_stdout = None
        try:
            parsed_stdout = json.loads(proc.stdout) if proc.stdout.strip() else None
        except Exception:
            parsed_stdout = None

        return {
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "parsed_stdout": parsed_stdout,
        }

    def listen_once(self) -> dict[str, Any]:
        Path(DEFAULT_WAV_DIR).mkdir(parents=True, exist_ok=True)

        self.vad.reset()

        runtime_status = load_runtime_status()
        runtime_status = cleanup_expired_session(runtime_status)

        if (
            runtime_status.get("listening_blocked")
            and runtime_status.get("block_reason") == "tts"
            and runtime_status.get("current_state") != "speaking"
        ):
            runtime_status["tts_active"] = False
            runtime_status["tts_source"] = None
            runtime_status["listening_blocked"] = False
            runtime_status["block_reason"] = None
            if runtime_status.get("last_error") == "listening_blocked:tts":
                runtime_status["last_error"] = None

        runtime_status["hotword"] = hotword_backend_status(self.hotword_backend)

        if self.hotword_enabled and runtime_status["hotword"].get("available"):
            hotword_probe = detect_hotword(None, preferred_backend=self.hotword_backend)
            runtime_status["hotword"] = {
                **runtime_status["hotword"],
                "detected": bool(hotword_probe.get("detected", False)),
                "score": float(hotword_probe.get("score", 0.0)),
                "reason": hotword_probe.get("reason"),
            }
            log_voice_event(
                "hotword_probe",
                source="voice_runtime",
                current_state=runtime_status.get("current_state") or "idle",
                data={
                    "backend": self.hotword_backend,
                    "available": runtime_status["hotword"].get("available"),
                    "detected": runtime_status["hotword"].get("detected"),
                    "score": runtime_status["hotword"].get("score"),
                    "reason": runtime_status["hotword"].get("reason"),
                },
            )

        mark_runtime_state(
            runtime_status.get("current_state") or "idle",
            hotword=runtime_status.get("hotword"),
            session=runtime_status.get("session"),
        )

        if runtime_status.get("session") is not None:
            mark_runtime_state(
                runtime_status.get("current_state") or "idle",
                session=runtime_status.get("session"),
            )

        stopword_mode = False

        if runtime_status.get("listening_blocked"):
            block_reason = runtime_status.get("block_reason") or "unknown"
            if block_reason == "tts":
                stopword_mode = True
                mark_runtime_state(
                    "listening",
                    mic_health="starting",
                    vad_health="tts_stopword",
                    stt_health="unknown",
                    last_audio_device=self.device,
                    last_error=None,
                )
                log_voice_event(
                    "tts_stopword_listen",
                    source="voice_runtime",
                    current_state="listening",
                    data={"device": self.device, "block_reason": block_reason},
                )
            else:
                mark_runtime_state(
                    "idle",
                    mic_health="blocked",
                    vad_health="blocked",
                    stt_health="blocked",
                    last_audio_device=self.device,
                    last_error=f"listening_blocked:{block_reason}",
                )
                log_voice_event(
                    "error",
                    source="voice_runtime",
                    current_state="idle",
                    error=f"listening_blocked:{block_reason}",
                    data={"device": self.device, "block_reason": block_reason},
                )
                return {
                    "ok": True,
                    "stage": "listening_blocked",
                    "block_reason": block_reason,
                    "segment_captured": False,
                }

        mark_runtime_state(
            "listening",
            mic_health="starting",
            vad_health="ready",
            stt_health="unknown",
            last_audio_device=self.device,
            last_error=None,
        )
        log_voice_event(
            "runtime_started",
            source="voice_runtime",
            current_state="listening",
            data={"device": self.device, "rate": self.sample_rate, "frame_ms": self.frame_ms},
        )

        pre_roll: deque[bytes] = deque(maxlen=self.pre_roll_frames)
        segment_frames: list[bytes] = []

        speech_started = False
        total_frames_seen = 0
        max_idle_frames = max(1, int((self.max_idle_seconds * 1000) / self.frame_ms))
        max_segment_frames = max(1, int((self.max_segment_seconds * 1000) / self.frame_ms))
        min_segment_frames = 20

        hotword_probe_frames = 0
        hotword_gate_active = bool(
            self.hotword_enabled
            and runtime_status.get("hotword", {}).get("available")
            and not (runtime_status.get("session") or {}).get("active", False)
        )
        hotword_detected = False
        hotword_gate_limit = max(1, self.hotword_gate_frames)

        try:
            for chunk in frame_stream(
                device=self.device,
                rate=self.sample_rate,
                channels=self.channels,
                frame_ms=self.frame_ms,
                sample_width=self.sample_width,
            ):
                total_frames_seen += 1

                if self.hotword_enabled and total_frames_seen <= 5 and runtime_status.get("hotword", {}).get("available"):
                    hotword_live = detect_hotword(
                        chunk,
                        preferred_backend=self.hotword_backend,
                        threshold=self.hotword_threshold,
                        target_model=self.hotword_target_model,
                    )
                    runtime_status["hotword"] = {
                        **runtime_status.get("hotword", {}),
                        "detected": bool(hotword_live.get("detected", False)),
                        "score": float(hotword_live.get("score", 0.0)),
                        "reason": hotword_live.get("reason"),
                        "best_match": hotword_live.get("best_match"),
                        "selected_match": hotword_live.get("selected_match"),
                        "target_model": self.hotword_target_model,
                    }
                    hotword_probe_frames += 1
                    if hotword_live.get("detected"):
                        hotword_detected = True
                        log_voice_event(
                            "hotword_detected",
                            source="voice_runtime",
                            current_state="listening",
                            data={
                                "frame_index": total_frames_seen,
                                "backend": self.hotword_backend,
                                "score": hotword_live.get("score"),
                                "best_match": hotword_live.get("best_match"),
                                "selected_match": hotword_live.get("selected_match"),
                                "target_model": self.hotword_target_model,
                            },
                        )

                    log_voice_event(
                        "hotword_probe_live",
                        source="voice_runtime",
                        current_state="listening",
                        data={
                            "frame_index": total_frames_seen,
                            "backend": self.hotword_backend,
                            "detected": hotword_live.get("detected"),
                            "score": hotword_live.get("score"),
                            "best_match": hotword_live.get("best_match"),
                            "selected_match": hotword_live.get("selected_match"),
                            "target_model": self.hotword_target_model,
                            "reason": hotword_live.get("reason"),
                        },
                    )
                    mark_runtime_state(
                        runtime_status.get("current_state") or "idle",
                        hotword=runtime_status.get("hotword"),
                        session=runtime_status.get("session"),
                    )

                    if hotword_gate_active and not hotword_detected:
                        if hotword_probe_frames >= hotword_gate_limit:
                            mark_runtime_state(
                                "idle",
                                mic_health="ok",
                                vad_health="hotword_gate",
                                stt_health="idle",
                                hotword=runtime_status.get("hotword"),
                                session=runtime_status.get("session"),
                                last_error="hotword_not_detected",
                            )
                            log_voice_event(
                                "hotword_gate_blocked",
                                source="voice_runtime",
                                current_state="idle",
                                error="hotword_not_detected",
                                data={
                                    "frames_checked": hotword_probe_frames,
                                    "backend": self.hotword_backend,
                                },
                            )
                            return {
                                "ok": True,
                                "stage": "hotword_not_detected",
                                "frames_seen": total_frames_seen,
                                "hotword": runtime_status.get("hotword"),
                                "segment_captured": False,
                            }
                        continue

                decision = self.vad.analyze_frame_dict(chunk)

                if not speech_started:
                    pre_roll.append(chunk)

                if decision["state"] == "speech_started":
                    speech_started = True
                    segment_frames.extend(pre_roll)
                    segment_frames.append(chunk)
                    mark_runtime_state(
                        "speech_detected",
                        mic_health="ok",
                        vad_health=decision["source"],
                        last_error=None,
                        timestamps={
                            "speech_started_at": datetime.utcnow().isoformat() + "Z",
                        },
                    )
                    log_voice_event(
                        "speech_started",
                        source="voice_runtime",
                        current_state="speech_detected",
                        data={"vad_source": decision["source"], "frame_ms": self.frame_ms},
                    )
                    continue

                if speech_started:
                    segment_frames.append(chunk)

                if speech_started and decision["state"] == "speech_ended":
                    if len(segment_frames) < min_segment_frames:
                        continue
                    mark_runtime_state(
                        "recording_segment",
                        mic_health="ok",
                        vad_health=decision["source"],
                        last_error=None,
                        timestamps={
                            "speech_ended_at": datetime.utcnow().isoformat() + "Z",
                        },
                    )
                    log_voice_event(
                        "speech_ended",
                        source="voice_runtime",
                        current_state="recording_segment",
                        data={
                            "vad_source": decision["source"],
                            "frames_seen": total_frames_seen,
                            "speech_end_silence_ms": self.state.get("speech_end_silence_ms"),
                            "vad_end_frames": self.vad_end_frames,
                            "frame_ms": self.frame_ms,
                            "segment_frames": len(segment_frames),
                            "segment_ms_estimate": len(segment_frames) * self.frame_ms,
                            "end_reason": "speech_ended",
                        },
                    )
                    break

                if speech_started and len(segment_frames) >= max_segment_frames:
                    mark_runtime_state(
                        "recording_segment",
                        mic_health="ok",
                        vad_health="segment_limit",
                        last_error=None,
                    )
                    break

                if (not speech_started) and total_frames_seen >= max_idle_frames:
                    mark_runtime_state(
                        "idle",
                        mic_health="ok",
                        vad_health="no_speech",
                        stt_health="idle",
                        last_error=None,
                    )
                    return {
                        "ok": True,
                        "stage": "no_speech",
                        "frames_seen": total_frames_seen,
                        "segment_captured": False,
                    }

        except Exception as e:
            mark_runtime_error(
                f"{type(e).__name__}: {e}",
                mic_health="error",
                vad_health="error",
            )
            return {
                "ok": False,
                "stage": "listen",
                "error": f"{type(e).__name__}: {e}",
            }

        if not segment_frames:
            mark_runtime_state(
                "idle",
                mic_health="ok",
                vad_health="empty_segment",
                stt_health="idle",
                last_error=None,
            )
            return {
                "ok": True,
                "stage": "empty_segment",
                "frames_seen": total_frames_seen,
                "segment_captured": False,
            }

        wav_path = make_wav_path()
        seg = record_segment(
            wav_path,
            segment_frames,
            rate=self.sample_rate,
            channels=self.channels,
            sample_width=self.sample_width,
        )
        log_voice_event(
            "segment_recorded",
            source="voice_runtime",
            current_state="transcribing",
            data={"segment_path": wav_path, "duration_ms": seg.get("duration_ms"), "frame_count": seg.get("frame_count")},
        )

        mark_runtime_state(
            "transcribing",
            mic_health="ok",
            vad_health="ok",
            stt_health="running",
            segment_path=wav_path,
            last_error=None,
        )

        stt = transcribe_wav_hybrid(wav_path, state=self.state, model_path_pl=self.model_path)
        log_voice_event(
            "stt_result",
            source="voice_runtime",
            current_state="transcribing",
            transcript=stt.get("transcript"),
            error=stt.get("error"),
            data={
                "empty_result": stt.get("empty_result"),
                "latency_ms": stt.get("latency_ms"),
                "wav_path": wav_path,
                "query_source": stt.get("query_source"),
                "query_scores": stt.get("query_scores"),
                "query_final": stt.get("query_final"),
                "command_boundary_sec": stt.get("command_boundary_sec"),
                "transcript_pl": stt.get("transcript_pl"),
                "transcript_en": stt.get("transcript_en"),
                "transcript_en_tail": stt.get("transcript_en_tail"),
                "tail_error": stt.get("tail_error"),
            },
        )

        if not stt.get("ok"):
            mark_runtime_error(
                str(stt.get("error", "stt_failed")),
                mic_health="ok",
                vad_health="ok",
                stt_health="error",
                segment_path=wav_path,
                last_transcript="",
            )
            log_voice_event(
                "error",
                source="voice_runtime",
                current_state="transcribing",
                error=str(stt.get("error", "stt_failed")),
                data={"wav_path": wav_path},
            )
            return {
                "ok": False,
                "stage": "stt",
                "segment": seg,
                "stt": stt,
            }

        transcript = (stt.get("transcript") or "").strip()

        if stopword_mode:
            if is_tts_stop_command(transcript):
                stop_result = stop_active_tts_session()
                mark_runtime_state(
                    "idle",
                    mic_health="ok",
                    vad_health="ok",
                    stt_health="ok",
                    segment_path=wav_path,
                    last_transcript=transcript,
                    last_route="tts_stop",
                    action_taken="stop_tts",
                    last_reply_text="Zatrzymuję mówienie.",
                    last_error=None,
                    timestamps={
                        "executed_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
                log_voice_event(
                    "tts_stopword_triggered",
                    source="voice_runtime",
                    current_state="idle",
                    transcript=transcript,
                    route="tts_stop",
                    action_taken="stop_tts",
                    reply_text="Zatrzymuję mówienie.",
                    data={"stop_result": stop_result},
                )
                return {
                    "ok": True,
                    "stage": "tts_stopped",
                    "segment": seg,
                    "stt": stt,
                    "route": "tts_stop",
                    "action_taken": "stop_tts",
                    "reply_text": "Zatrzymuję mówienie.",
                }

            mark_runtime_state(
                "idle",
                mic_health="ok",
                vad_health="ok",
                stt_health="ok",
                segment_path=wav_path,
                last_transcript="",
                last_error=None,
            )
            return {
                "ok": True,
                "stage": "tts_ignored",
                "segment": seg,
                "stt": stt,
                "route": "tts_guard",
                "action_taken": "ignored",
                "reply_text": "",
            }

        mark_runtime_state(
            "routing",
            mic_health="ok",
            vad_health="ok",
            stt_health="ok",
            segment_path=wav_path,
            last_transcript=transcript,
            last_error=None,
            timestamps={
                "transcribed_at": datetime.utcnow().isoformat() + "Z",
            },
        )

        if not transcript:
            mark_runtime_state(
                "cooldown",
                mic_health="ok",
                vad_health="ok",
                stt_health="empty_result",
                segment_path=wav_path,
                last_transcript="",
                last_route="stt_empty",
                action_taken="cooldown",
                last_reply_text="",
                cooldown_until=datetime.utcnow().isoformat() + "Z",
                last_error="empty_transcript",
            )
            log_voice_event(
                "cooldown_entered",
                source="voice_runtime",
                current_state="cooldown",
                route="stt_empty",
                action_taken="cooldown",
                error="empty_transcript",
                data={"wav_path": wav_path},
            )
            return {
                "ok": True,
                "stage": "empty_text",
                "segment": seg,
                "stt": stt,
                "route": "stt_empty",
                "action_taken": "cooldown",
                "reply_text": "",
            }

        daemon = self.run_voice_daemon(transcript)
        daemon_data = daemon.get("parsed_stdout") or {}
        daemon_route = daemon_data.get("route")
        daemon_action = daemon_data.get("action_taken")
        daemon_reply = daemon_data.get("reply_text")
        daemon_error = daemon_data.get("error")
        daemon_needs_tts = bool(daemon_data.get("needs_tts", False))

        current_runtime_status = load_runtime_status()
        current_runtime_status = update_session_after_daemon(
            current_runtime_status,
            daemon_route=daemon_route,
            daemon_action=daemon_action,
            daemon_data=daemon_data,
        )

        tts_result = None
        if daemon_needs_tts and daemon_reply:
            tts_result = speak_with_arbiter(
                daemon_reply,
                preferred_provider=str(self.state.get("tts_provider", "piper")),
                play_audio=True,
                source="voice_runtime",
                tts_fx_mode=str(self.state.get("tts_fx_mode", "standard")),
            )
            log_voice_event(
                "daemon_result",
                source="voice_runtime",
                current_state="speaking",
                transcript=transcript,
                route=daemon_route,
                action_taken="tts_playback",
                reply_text=daemon_reply,
                error=tts_result.get("error") if tts_result else None,
                data={"tts_ok": tts_result.get("ok") if tts_result else False},
            )

        if daemon_route:
            log_voice_event(
                "route_selected",
                source="voice_runtime",
                current_state="routing",
                transcript=transcript,
                route=daemon_route,
                data={"source": "daemon_result"},
            )

        if daemon_action:
            log_voice_event(
                "dispatch_selected",
                source="voice_runtime",
                current_state="executing",
                transcript=transcript,
                route=daemon_route,
                action_taken=daemon_action,
                reply_text=daemon_reply,
                error=daemon_error,
                data={"source": "daemon_result"},
            )

        mark_runtime_state(
            "executing",
            mic_health="ok",
            vad_health="ok",
            stt_health="ok",
            segment_path=wav_path,
            last_transcript=transcript,
            last_route=daemon_route,
            action_taken=daemon_action,
            last_reply_text=daemon_reply,
            last_error=daemon_error,
            session=current_runtime_status.get("session"),
            timestamps={
                "executed_at": datetime.utcnow().isoformat() + "Z",
            },
        )
        log_voice_event(
            "daemon_result",
            source="voice_runtime",
            current_state="executing",
            transcript=transcript,
            route=daemon_route,
            action_taken=daemon_action,
            reply_text=daemon_reply,
            error=daemon_error,
            data={"returncode": daemon.get("returncode")},
        )

        time.sleep(max(0, self.cooldown_ms) / 1000.0)

        mark_runtime_state(
            "idle",
            mic_health="ok",
            vad_health="ok",
            stt_health="ok",
            segment_path=wav_path,
            last_transcript=transcript,
            last_route=daemon_route,
            action_taken=daemon_action,
            last_reply_text=daemon_reply,
            last_error=daemon_error,
            session=current_runtime_status.get("session"),
        )

        return {
            "ok": True,
            "stage": "done",
            "segment": seg,
            "stt": stt,
            "daemon": daemon,
            "tts": tts_result,
            "route": daemon_route,
            "action_taken": daemon_action,
            "reply_text": daemon_reply,
        }


def one_cycle() -> dict[str, Any]:
    runtime = VoiceRuntime()
    return runtime.listen_once()


def main() -> int:
    print("VOICE_RUNTIME_START")
    print("Ctrl+C aby zakończyć")
    try:
        while True:
            result = one_cycle()
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print("-" * 60)
    except KeyboardInterrupt:
        print("VOICE_RUNTIME_STOP")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
