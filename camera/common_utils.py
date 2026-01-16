# camera/common_utils.py
# Wspólne funkcje niskopoziomowe (ETAP 3)

import os
import subprocess

from camera.config import (
    STREAM_DIR,
    HLS_PLAYLIST,
    PI_HOST,
    SSH_OPTS,
)


def hls_ready() -> bool:
    try:
        return os.path.isfile(HLS_PLAYLIST) and os.path.getsize(HLS_PLAYLIST) > 0
    except Exception:
        return False


def kill_remote_rpicam():
    """
    Twarde ubijanie rpicam-vid na Raspberry Pi (fallback bezpieczeństwa)
    """
    cmd = (
        "pkill -TERM -f rpicam-vid 2>/dev/null || true; "
        "sleep 0.3; "
        "pkill -KILL -f rpicam-vid 2>/dev/null || true"
    )
    try:
        subprocess.run(
            ["ssh", *SSH_OPTS, PI_HOST, cmd],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except Exception:
        pass
