# camera/pipeline/stream_pipeline.py
# ETAP 3 – Pipeline kamery (Pi -> ffmpeg -> HLS + RTSP)

import subprocess
import time
from typing import Optional

from camera.config import (
    PI_HOST,
    SSH_OPTS,
    PROFILES,
    DEFAULT_PROFILE,
    RPICAM_GAIN,
    RPICAM_BRIGHTNESS,
    RPICAM_SHARPNESS,
    RPICAM_CONTRAST,
    RPICAM_SATURATION,
    RPICAM_DENOISE,
    HLS_PLAYLIST,
    HLS_SEGMENT_PATTERN,
    LOG_FFMPEG_HLS,
    LOG_SSH_PI,
)

from camera.common_utils import kill_remote_rpicam, hls_ready


class StreamPipeline:
    def __init__(self):
        self.proc_pi: Optional[subprocess.Popen] = None
        self.proc_hls: Optional[subprocess.Popen] = None
        self.profile: str = DEFAULT_PROFILE

    # =========================
    # BUILD COMMANDS
    # =========================

    def _profile_cfg(self) -> dict:
        return PROFILES.get(self.profile, PROFILES[DEFAULT_PROFILE])

    def _build_pi_cmd(self) -> str:
        cfg = self._profile_cfg()
        w, h, fps = cfg["w"], cfg["h"], cfg["fps"]
        intra = fps

        return (
            "rpicam-vid -t 0 "
            "--codec h264 "
            "--profile baseline "
            f"--intra {intra} "
            "--inline "
            f"--width {w} --height {h} --framerate {fps} "
            "--exposure sport --awb auto "
            f"--gain {RPICAM_GAIN} "
            f"--brightness {RPICAM_BRIGHTNESS} "
            f"--sharpness {RPICAM_SHARPNESS} "
            f"--contrast {RPICAM_CONTRAST} "
            f"--saturation {RPICAM_SATURATION} "
            f"--denoise {RPICAM_DENOISE} "
            "-o -"
        )

    def _build_ffmpeg_cmd(self) -> list:
        cfg = self._profile_cfg()
        hls_time = cfg["hls_time"]
        hls_list = cfg["hls_list"]

        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "info",
            "-fflags", "+genpts",
            "-use_wallclock_as_timestamps", "1",
            "-f", "h264",
            "-i", "pipe:0",
            "-map", "0:v",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-g", "30",
            "-keyint_min", "30",
            "-f", "tee",
            (
                "[f=hls:"
                f"hls_time={hls_time}:"
                f"hls_list_size={hls_list}:"
                "hls_flags=delete_segments+independent_segments+omit_endlist:"
                f"hls_segment_filename={HLS_SEGMENT_PATTERN}]"
                f"{HLS_PLAYLIST}|"
                "[f=rtsp:rtsp_transport=tcp:rtsp_flags=listen]"
                "rtsp://127.0.0.1:8554/motion"
            ),
        ]

    # =========================
    # LIFECYCLE
    # =========================

    def start(self, profile: Optional[str] = None) -> bool:
        if self.is_running():
            return True

        if profile:
            self.profile = profile

        retries = [0.5, 1.0, 2.0]

        for attempt, delay in enumerate(retries, start=1):
            try:
                kill_remote_rpicam()

                pi_log = open(LOG_SSH_PI, "ab", buffering=0)
                hls_log = open(LOG_FFMPEG_HLS, "ab", buffering=0)

                ssh_cmd = ["ssh", *SSH_OPTS, PI_HOST, self._build_pi_cmd()]

                self.proc_pi = subprocess.Popen(
                    ssh_cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=pi_log,
                )

                time.sleep(1)

                if self.proc_pi.poll() is not None:
                    raise RuntimeError("rpicam exited early")

                self.proc_hls = subprocess.Popen(
                    self._build_ffmpeg_cmd(),
                    stdin=self.proc_pi.stdout,
                    stdout=hls_log,
                    stderr=subprocess.STDOUT,
                    bufsize=0,
                    start_new_session=True,
                    close_fds=True,
                )

                self.proc_pi.stdout.close()

                for _ in range(20):
                    time.sleep(1)

                    if self.proc_pi.poll() is not None:
                        raise RuntimeError("rpicam exited")

                    if self.proc_hls.poll() is not None:
                        raise RuntimeError("ffmpeg exited")

                    if hls_ready():
                        return True

                raise RuntimeError("hls not ready")

            except Exception:
                try:
                    self.stop()
                except Exception:
                    pass

                if attempt < len(retries):
                    time.sleep(delay)
                    continue

                return False


    def stop(self):
        for attr in ("proc_hls", "proc_pi"):
            p = getattr(self, attr)
            if not p:
                continue
            try:
                p.terminate()
                p.wait(timeout=2)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass
            setattr(self, attr, None)

        kill_remote_rpicam()

    def is_running(self) -> bool:
        return (
            self.proc_pi is not None
            and self.proc_hls is not None
            and self.proc_pi.poll() is None
            and self.proc_hls.poll() is None
        )
