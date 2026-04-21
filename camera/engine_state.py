# camera/engine_state.py
# ETAP 2 – Centralne źródło prawdy o stanie silnika
# Defaulty feature-flag są czytane z camera/config.py (wykonywany przy imporcie)

from enum import Enum, auto
from dataclasses import dataclass, field
import threading
import time


class EngineMode(Enum):
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    RESTARTING = auto()
    ERROR = auto()


def _cfg_bool(name: str, fallback: bool) -> bool:
    try:
        import camera.config as cfg
        return bool(getattr(cfg, name, fallback))
    except Exception:
        return bool(fallback)


def _motion_enabled_default() -> bool:
    return _cfg_bool("MOTION_ENABLED_DEFAULT", True)


def _motion_photo_default() -> bool:
    return _cfg_bool("MOTION_PHOTO_ENABLED_DEFAULT", True)


def _motion_record_default() -> bool:
    return _cfg_bool("MOTION_RECORD_ENABLED_DEFAULT", False)


@dataclass
class EngineState:
    mode: EngineMode = EngineMode.IDLE
    started_at: float = field(default_factory=time.time)
    stream_started_at: float = 0.0

    stream: bool = False
    mqtt_ok: bool = False

    profile: str = ""

    motion_enabled: bool = field(default_factory=_motion_enabled_default)
    motion_photo_enabled: bool = field(default_factory=_motion_photo_default)
    motion_record_enabled: bool = field(default_factory=_motion_record_default)

    manual_recording: bool = False
    recording_active: bool = False

    photos_taken: int = 0
    recordings_count: int = 0
    segments_session: int = 0

    crash_count: int = 0
    restart_count: int = 0
    last_crash_at: float = 0.0
    retry_count: int = 0

    last_event: str = "boot"
    last_error: str = ""

    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def set_mode(self, mode: EngineMode, event: str = "", error: str = ""):
        with self.lock:
            self.mode = mode
            self.stream = (mode == EngineMode.RUNNING)
            if event:
                self.last_event = event
            if error:
                self.last_error = error

    def is_running(self) -> bool:
        return self.mode == EngineMode.RUNNING

    def is_starting(self) -> bool:
        return self.mode in (EngineMode.STARTING, EngineMode.RESTARTING)

    def is_stopping(self) -> bool:
        return self.mode == EngineMode.STOPPING

    def mark_stream_started(self):
        with self.lock:
            self.stream = True
            self.stream_started_at = time.time()
            self.mode = EngineMode.RUNNING
            self.last_event = "stream_started"
            self.last_error = ""

    def mark_stream_stopped(self, reason: str = "", error: str = ""):
        with self.lock:
            self.stream = False
            self.manual_recording = False
            self.recording_active = False
            self.mode = EngineMode.IDLE
            if reason:
                self.last_event = reason
            if error:
                self.last_error = error

    def uptime(self) -> int:
        return int(time.time() - self.started_at)

    def stream_uptime(self) -> int:
        if not self.stream_started_at:
            return 0
        return int(time.time() - self.stream_started_at)
