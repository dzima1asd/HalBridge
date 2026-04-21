from pathlib import Path
# camera/config.py
# Centralna konfiguracja systemu kamery
# ETAP 1 – bez zmiany logiki

# ========================= MQTT =========================

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

BASE_TOPIC = "hal/stream"
T_CMD = f"{BASE_TOPIC}/cmd"
T_STATUS = f"{BASE_TOPIC}/status"
T_ACK = f"{BASE_TOPIC}/ack"
T_LOG = f"{BASE_TOPIC}/log"
T_DIAG = f"{BASE_TOPIC}/diag"
T_HEALTH = f"{BASE_TOPIC}/health"
T_EVENT = f"{BASE_TOPIC}/event"


# ========================= SSH / PI =========================

PI_HOST = "zero@192.168.100.16"

SSH_OPTS = [
    "-n",
    "-T",
    "-o", "ConnectTimeout=5",
    "-o", "ServerAliveInterval=10",
    "-o", "ServerAliveCountMax=2",
    "-o", "BatchMode=yes",
]


# ========================= HTTP / STREAM =========================

HTTP_BIND = "0.0.0.0"
HTTP_PORT = 8081

LOCAL_STREAM_URL = f"http://127.0.0.1:{HTTP_PORT}/stream.m3u8"
MOTION_STREAM_URL = "rtsp://127.0.0.1:8554/motion"


# ========================= ŚCIEŻKI =========================

BASE_DIR = "/home/hal/HALbridge/media"

STREAM_DIR = f"{BASE_DIR}/stream"
LOG_DIR = f"{BASE_DIR}/logs"
PHOTO_DIR = f"{BASE_DIR}/photos"
REC_DIR = f"{BASE_DIR}/recordings"

HLS_PLAYLIST = f"{STREAM_DIR}/stream.m3u8"
HLS_SEGMENT_PATTERN = f"{STREAM_DIR}/stream%06d.ts"

LOG_FFMPEG_HLS = f"{LOG_DIR}/ffmpeg_hls.log"
LOG_SSH_PI = f"{LOG_DIR}/pi_ssh.log"
LOG_MOTION = f"{LOG_DIR}/motion.log"


# ========================= TAILSCALE =========================

TAILSCALE_BIN = "/usr/bin/tailscale"
TAILSCALE_PORT = HTTP_PORT


# ========================= PROFILE STREAMU =========================

PROFILES = {
    "low": {
        "w": 640,
        "h": 480,
        "fps": 30,
        "hls_time": 2,
        "hls_list": 6,
    },
    "med": {
        "w": 1280,
        "h": 720,
        "fps": 30,
        "hls_time": 2,
        "hls_list": 6,
    },
    "high": {
        "w": 1920,
        "h": 1080,
        "fps": 30,
        "hls_time": 2,
        "hls_list": 6,
    },
}

DEFAULT_PROFILE = "med"


# ========================= PARAMETRY OBRAZU =========================

RPICAM_GAIN = "2.0"
RPICAM_BRIGHTNESS = "0.2"
RPICAM_SHARPNESS = "1.4"
RPICAM_CONTRAST = "1.4"
RPICAM_SATURATION = "1.15"
RPICAM_DENOISE = "cdn_off"


# ========================= ZDJĘCIA =========================

PHOTO_WIDTH = 4056
PHOTO_HEIGHT = 3040
PHOTO_QUALITY = 95


# ========================= DETEKCJA RUCHU =========================

MOTION_ENABLED_DEFAULT = True
MOTION_SCENE_THRESHOLD = 0.90
MOTION_POLL_RETRY_SEC = 2
MOTION_COOLDOWN_SEC = 1

MOTION_PHOTO_ENABLED_DEFAULT = True
MOTION_RECORD_ENABLED_DEFAULT = True
MOTION_RECORD_SECONDS = 12


# ========================= WATCHDOG =========================

WATCHDOG_INTERVAL_SEC = 1.0


# Auto-record (motion): nagrywaj dopóki jest ruch, ale tnij na kawałki
AUTO_RECORD_MAX_SEC = 15 * 60   # max długość jednego pliku (15 min)
AUTO_RECORD_IDLE_SEC = 20

# ===== Camera tuning (keep motion timings/sensitivity unchanged) =====
# Video (indoor, artificial light): start values
RPICAM_EXPOSURE = "normal"
RPICAM_AWB = "auto"
RPICAM_SHUTTER_US = 10000   # 10ms (dobry start pod 50Hz LED, mniej migotania)

# Photo (sport): start values
PHOTO_EXPOSURE = "sport"
PHOTO_AWB = "auto"
PHOTO_SHUTTER_US = 5000     # 5ms (szybciej, mniej rozmycia)


# Persisted engine state
STATE_FILE = str((Path.home()/"HALbridge/media/state/stream_engine_state.json").resolve())


# scp doesn't accept -n / -T, keep only compatible opts
SCP_OPTS = [x for x in SSH_OPTS if x not in ('-n','-T')]
