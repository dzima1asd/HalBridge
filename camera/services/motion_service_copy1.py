# camera/services/motion_service.py

import threading
import time
import subprocess
from typing import Optional

from camera.config import (
    MOTION_SCENE_THRESHOLD,
    MOTION_COOLDOWN_SEC,
    MOTION_POLL_RETRY_SEC,
    LOG_MOTION,
    LOCAL_STREAM_URL,
)


class MotionService:
    def __init__(
        self,
        *,
        stop_event: threading.Event,
        is_stream_running,
        is_http_running,
        hls_ready,
        count_segments,
        on_motion_cb,
        log,
    ):
        self.stop_event = stop_event
        self.is_stream_running = is_stream_running
        self.is_http_running = is_http_running
        self.hls_ready = hls_ready
        self.count_segments = count_segments
        self.on_motion_cb = on_motion_cb
        self.log = log

        self.enabled = True
        self.thread: Optional[threading.Thread] = None
        self.proc_motion: Optional[subprocess.Popen] = None

        self.last_motion_ts = 0.0
        self.last_motion_start_ts = 0.0

        self.motion_allowed = threading.Event()
        self.motion_allowed.set()

    # ---------- API ----------

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.enabled = False
        self.motion_allowed.clear()
        self._stop_proc()

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        if not self.enabled:
            self._stop_proc()

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    # ---------- INTERNAL ----------

    def _stop_proc(self):
        p = self.proc_motion
        if not p:
            return
        try:
            p.terminate()
            p.wait(timeout=2.0)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
        finally:
            self.proc_motion = None

    def _build_motion_ffmpeg_cmd(self):
        # KLUCZ: metadata=print jest na poziomie INFO -> -loglevel error ucina te linie.
        # Dajemy loglevel=info i kierujemy output filtra na stdout (file=-).
        vf = f"select='gt(scene,{MOTION_SCENE_THRESHOLD})',metadata=print:file=-"

        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "info",
            "-nostdin",
            # HLS/HTTP: reconnect
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "2",
            "-rw_timeout", "5000000",
            "-fflags", "+genpts",
            "-i", LOCAL_STREAM_URL,
            "-an",
            "-vf", vf,
            "-f", "null",
            "-",
        ]

    def _wait_until_ready(self):
        while not self.stop_event.is_set():
            if (
                self.enabled
                and self.is_stream_running()
                and self.is_http_running()
                and self.hls_ready()
                and self.count_segments() >= 3
            ):
                return True
            time.sleep(0.5)
        return False

    def _worker(self):
        self.log("motion: started")
        time.sleep(1.5)

        if not self._wait_until_ready():
            self.log("motion: aborted before ready")
            return

        while not self.stop_event.is_set():
            if not self.enabled:
                time.sleep(0.5)
                continue

            if not self.motion_allowed.wait(timeout=1.0):
                continue

            now = time.time()
            if now - self.last_motion_start_ts < 3.0:
                time.sleep(0.5)
                continue
            self.last_motion_start_ts = now

            try:
                with open(LOG_MOTION, "ab", buffering=0):
                    self.proc_motion = subprocess.Popen(
                        self._build_motion_ffmpeg_cmd(),
                        stdout=subprocess.PIPE,      # <-- tu lecą linie metadata=print:file=-
                        stderr=subprocess.DEVNULL,   # <-- nie zalewamy świata
                        bufsize=1,
                        text=True,
                        start_new_session=True,
                        close_fds=True,
                    )

                    while not self.stop_event.is_set():
                        if not self.enabled or not self.is_stream_running():
                            break

                        if self.proc_motion.poll() is not None:
                            self.log("motion: ffmpeg exited, restarting")
                            time.sleep(1.0)
                            break

                        line = self.proc_motion.stdout.readline() if self.proc_motion.stdout else ""
                        if not line:
                            time.sleep(0.05)
                            continue

                        line = line.strip()
                        if "lavfi.scene_score" in line:
                            now = time.time()
                            if now - self.last_motion_ts < MOTION_COOLDOWN_SEC:
                                continue
                            self.last_motion_ts = now
                            self.on_motion_cb(line)

            except Exception as e:
                self.log(f"motion: error: {e!r}")
            finally:
                self._stop_proc()
                time.sleep(MOTION_POLL_RETRY_SEC)

        self.log("motion: stopped")

