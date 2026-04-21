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
    PHOTO_EXPOSURE,
    PHOTO_AWB,
    PHOTO_SHUTTER_US,
    LOCAL_STREAM_URL,
    SSH_OPTS,
    SCP_OPTS,
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
        local_path = os.path.join(PHOTO_DIR, filename)

        # Jeśli stream działa, NIE dotykamy kamery drugi raz.
        # Bierzemy klatkę z HLS (ffmpeg) i zapisujemy lokalnie.
        try:
            if self.is_stream_running():
                self.log("photo: snapshot from HLS (ffmpeg)")
                r = subprocess.run(
                    ["ffmpeg", "-hide_banner", "-loglevel", "error",
                     "-y",
                     "-i", "http://127.0.0.1:8081/stream.m3u8",
                     "-frames:v", "1",
                     "-q:v", "2",
                     local_path],
                    capture_output=True,
                    timeout=12,
                    text=True
                )
                if r.returncode == 0 and os.path.isfile(local_path) and os.path.getsize(local_path) > 0:
                    return local_path
                self.log(f"photo: ffmpeg error: {(r.stderr or r.stdout).strip()}")
                return None
        except Exception as e:
            self.log(f"photo: ffmpeg exception: {e}")
            return None

        # Fallback: stream nie działa -> robimy zdjęcie na Pi kamerą
        remote_path = f"/tmp/{filename}"
        photo_cmd = (
            f"rpicam-jpeg -t 1 "
            f"--width {PHOTO_WIDTH} --height {PHOTO_HEIGHT} "
            f"--quality {PHOTO_QUALITY} "
            f"--awb auto --denoise off --shutter 10000 --exposure normal "
            f"-o {remote_path}"
        )

        self.log("photo: capturing on Pi (camera)")
        r = subprocess.run(
            ["ssh", *SSH_OPTS, PI_HOST, photo_cmd],
            capture_output=True,
            timeout=25,
            text=True
        )
        if r.returncode != 0:
            self.log(f"photo: Pi error: {(r.stderr or r.stdout).strip()}")
            return None

        self.log("photo: downloading via scp")
        r2 = subprocess.run(
            ["scp", *SSH_OPTS, f"{PI_HOST}:{remote_path}", local_path],
            capture_output=True,
            timeout=40,
            text=True
        )

        subprocess.run(
            ["ssh", *SSH_OPTS, PI_HOST, f"rm -f {remote_path}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10
        )

        if r2.returncode != 0:
            self.log(f"photo: scp error: {(r2.stderr or r2.stdout).strip()}")
            return None

        return local_path
