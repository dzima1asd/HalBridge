# camera/services/recorder_service.py

import os
import subprocess
import threading
from datetime import datetime
from typing import Optional


class RecorderService:
    def __init__(
        self,
        *,
        is_stream_running,
        is_http_running,
        hls_ready,
        log,
        rec_dir,
        local_stream_url,
    ):
        self.is_stream_running = is_stream_running
        self.is_http_running = is_http_running
        self.hls_ready = hls_ready
        self.log = log
        self.rec_dir = rec_dir
        self.local_stream_url = local_stream_url

        self.proc: Optional[subprocess.Popen] = None
        self.last_path: Optional[str] = None
        self._lock = threading.Lock()

    def start_recording(self, seconds: Optional[int] = None) -> Optional[str]:
        with self._lock:
            if not self.is_stream_running():
                self.log("record: stream not running")
                return None

            if not self.is_http_running() or not self.hls_ready():
                self.log("record: HLS not ready")
                return None

            if self.proc and self.proc.poll() is None:
                self.log("record: already recording")
                return self.last_path

            os.makedirs(self.rec_dir, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{ts}.mp4"
            out_path = os.path.join(self.rec_dir, filename)

            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "error",
                "-y",
            ]

            if seconds and seconds > 0:
                cmd += ["-t", str(int(seconds))]

            cmd += [
                "-i", self.local_stream_url,
                "-c", "copy",
                "-movflags", "+frag_keyframe+empty_moov+default_base_moof",
                "-f", "mp4",
                out_path,
            ]

            self.log(f"record: start -> {out_path}")

            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
                close_fds=True,
            )

            self.last_path = out_path

            if seconds and seconds > 0:
                threading.Thread(
                    target=self._wait_and_cleanup,
                    args=(self.proc,),
                    daemon=True,
                ).start()

            return out_path

    def stop_recording(self) -> bool:
        with self._lock:
            p = self.proc
            if not p:
                return True

            if p.poll() is not None:
                self.proc = None
                return True

            self.log("record: stop (graceful)")
            try:
                if p.stdin:
                    p.stdin.write("q\n")
                    p.stdin.flush()
                p.wait(timeout=6.0)
            except Exception:
                try:
                    p.terminate()
                    p.wait(timeout=2.0)
                except Exception:
                    try:
                        p.kill()
                    except Exception:
                        pass
            finally:
                self.proc = None

        return True

    def _wait_and_cleanup(self, proc: subprocess.Popen):
        try:
            proc.wait()
        except Exception:
            pass

        with self._lock:
            if self.proc is proc:
                self.log("record: finished (auto)")
                self.proc = None

    def is_recording(self) -> bool:
        with self._lock:
            return self.proc is not None and self.proc.poll() is None

    start = start_recording
    stop = stop_recording
