import threading
import time
import subprocess
import re
from typing import Optional

from camera.config import (
    MOTION_SCENE_THRESHOLD,
    MOTION_COOLDOWN_SEC,
    MOTION_POLL_RETRY_SEC,
    MOTION_STREAM_URL,
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

        self.photo_enabled = True
        self.record_enabled = False
        self.enabled = True

        self.thread: Optional[threading.Thread] = None
        self.proc_motion: Optional[subprocess.Popen] = None

        self.last_motion_ts = 0.0
        self.last_motion_start_ts = 0.0

        self._ydif_re = re.compile(r"lavfi\.signalstats\.YDIF=([0-9]*\.?[0-9]+)")
        self._ydif_threshold = float(MOTION_SCENE_THRESHOLD)
        self._ydif_hits = 0
        self._ydif_hits_required = 2
        self._last_ydif_log_ts = 0.0

    def start(self):
        self.enabled = True
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def stop(self):
        self.enabled = False
        self._stop_proc()

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)
        if not self.enabled:
            self._stop_proc()

    def set_actions(self, photo: bool, record: bool):
        self.photo_enabled = bool(photo)
        self.record_enabled = bool(record)

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

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
        vf = "tblend=all_mode=difference,signalstats,metadata=print:file=-"

        return [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-nostats",
            "-loglevel", "error",
            "-fflags", "+genpts",
            "-rtsp_transport", "tcp", "-i", MOTION_STREAM_URL,
            "-an",
            "-vf", vf,
            "-f", "null",
            "-"
        ]

    def _maybe_log_ydif(self, ydif: float):
        now = time.time()
        if now - self._last_ydif_log_ts >= 5.0:
            self._last_ydif_log_ts = now
            self.log(f"motion: ydif={ydif:.3f} thr={self._ydif_threshold:.3f} hits={self._ydif_hits}/{self._ydif_hits_required}")

    def _worker(self):
        self.log("motion: worker started")
        time.sleep(1.5)

        while not self.stop_event.is_set():

            if not self.enabled:
                time.sleep(0.5)
                continue

            if not (
                self.is_stream_running()
                and self.is_http_running()
                and self.hls_ready()
                and self.count_segments() >= 3
            ):
                time.sleep(0.5)
                continue

            now = time.time()
            if now - self.last_motion_start_ts < 3.0:
                time.sleep(0.5)
                continue

            self.last_motion_start_ts = now

            warmup_until = time.time() + 10.0
            self._ydif_hits = 0

            try:
                self.proc_motion = subprocess.Popen(
                    self._build_motion_ffmpeg_cmd(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
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
                        break

                    line = self.proc_motion.stdout.readline()
                    if not line:
                        time.sleep(0.05)
                        continue

                    line = line.strip()

                    if time.time() < warmup_until:
                        continue

                    m = self._ydif_re.search(line)
                    if not m:
                        continue

                    try:
                        ydif = float(m.group(1))
                    except Exception:
                        continue

                    self._maybe_log_ydif(ydif)

                    now = time.time()
                    if now - self.last_motion_ts < MOTION_COOLDOWN_SEC:
                        continue

                    if ydif >= self._ydif_threshold:
                        self._ydif_hits += 1
                    else:
                        if self._ydif_hits > 0:
                            self._ydif_hits -= 1

                    if self._ydif_hits < self._ydif_hits_required:
                        continue

                    self.last_motion_ts = now
                    self._ydif_hits = 0

                    if not self.photo_enabled and not self.record_enabled:
                        self.log("motion: detected but no actions enabled")
                        continue

                    self.on_motion_cb(f"ydif={ydif:.3f} thr={self._ydif_threshold:.3f}")

            except Exception as e:
                self.log(f"motion: error: {e!r}")

            finally:
                self._stop_proc()
                time.sleep(MOTION_POLL_RETRY_SEC)
