# camera/services/snapshot_service.py

import os
import subprocess
from datetime import datetime
from typing import Optional

from camera.config import (
    PHOTO_DIR,
    PHOTO_WIDTH,
    PHOTO_HEIGHT,
    PHOTO_QUALITY,
    LOCAL_STREAM_URL,
    SSH_OPTS,
    PI_HOST,
)


class SnapshotService:
    def __init__(self, *, is_stream_running, is_http_running, hls_ready, log):
        self.is_stream_running = is_stream_running
        self.is_http_running = is_http_running
        self.hls_ready = hls_ready
        self.log = log

    def take_photo(self) -> Optional[str]:
        os.makedirs(PHOTO_DIR, exist_ok=True)

        if self.is_stream_running():
            if not self.is_http_running() or not self.hls_ready():
                self.log("photo: stream active but HLS not ready")
                return None
            return self._photo_from_stream()

        return self._photo_from_camera()

    def _photo_from_stream(self) -> Optional[str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        out_path = os.path.join(PHOTO_DIR, filename)

        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-i", LOCAL_STREAM_URL,
            "-frames:v", "1",
            "-q:v", "2",
            out_path,
        ]

        self.log("photo: snapshot from stream")
        try:
            r = subprocess.run(cmd, timeout=8)
            if r.returncode != 0 or not os.path.isfile(out_path):
                self.log("photo: snapshot from stream FAILED")
                return None
        except Exception as e:
            self.log(f"photo: stream snapshot error: {e}")
            return None

        return out_path

    def _photo_from_camera(self) -> Optional[str]:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        remote_path = f"/tmp/{filename}"
        local_path = os.path.join(PHOTO_DIR, filename)

        photo_cmd = (
            f"rpicam-jpeg -t 1 "
            f"--width {PHOTO_WIDTH} --height {PHOTO_HEIGHT} "
            f"--quality {PHOTO_QUALITY} "
            f"--exposure normal --awb auto "
            f"-o {remote_path}"
        )

        self.log("photo: capturing on Pi (camera)")
        r = subprocess.run(
            ["ssh", *SSH_OPTS, PI_HOST, photo_cmd],
            capture_output=True,
            timeout=25,
        )
        if r.returncode != 0:
            self.log(f"photo: Pi error: {r.stderr.decode(errors='ignore')}")
            return None

        self.log("photo: downloading via scp")
        r2 = subprocess.run(
            ["scp", *SSH_OPTS, f"{PI_HOST}:{remote_path}", local_path],
            capture_output=True,
            timeout=40,
        )

        subprocess.run(
            ["ssh", *SSH_OPTS, PI_HOST, f"rm -f {remote_path}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if r2.returncode != 0:
            self.log(f"photo: scp error: {r2.stderr.decode(errors='ignore')}")
            return None

        return local_path
