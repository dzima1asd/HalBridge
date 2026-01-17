# camera/engine_state.py
# ETAP 2 – Centralne źródło prawdy o stanie silnika

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


@dataclass
class EngineState:
    # --- lifecycle ---
    mode: EngineMode = EngineMode.IDLE
    started_at: float = field(default_factory=time.time)
    stream_started_at: float = 0.0

    # --- flags ---
    stream: bool = False
    mqtt_ok: bool = False

    # --- profile ---
    profile: str = ""

    # --- motion / media ---
    motion_enabled: bool = True
    motion_photo_enabled: bool = True
    motion_record_enabled: bool = False

    manual_recording: bool = False
    recording_active: bool = False

    # --- stats ---
    photos_taken: int = 0
    recordings_count: int = 0
    segments_session: int = 0

    crash_count: int = 0
    restart_count: int = 0
    last_crash_at: float = 0.0
    retry_count: int = 0

    # --- events / errors ---
    last_event: str = "boot"
    last_error: str = ""

    # --- internal ---
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # =========================
    # Bezpieczne operacje stanu
    # =========================

    def set_mode(self, mode: EngineMode, event: str = "", error: str = ""):
        with self.lock:
            self.mode = mode
            # stream flag is derived from mode
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
