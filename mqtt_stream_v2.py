#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import signal
import threading
import subprocess
from collections import deque
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from datetime import datetime

import paho.mqtt.client as mqtt

# ===================== MQTT =====================
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

BASE = "hal/stream"
T_CMD = f"{BASE}/cmd"
T_STATUS = f"{BASE}/status"
T_ACK = f"{BASE}/ack"
T_LOG = f"{BASE}/log"
T_DIAG = f"{BASE}/diag"

# ===================== SYSTEM =====================
PI_HOST = "zero@192.168.100.16"
TAILSCALE_IP = "100.80.82.126"
HTTP_PORT = 8081

BASE_DIR = "/home/hal/HALbridge/media"
STREAM_DIR = f"{BASE_DIR}/stream"
LOG_DIR = f"{BASE_DIR}/logs"

HLS_PLAYLIST = f"{STREAM_DIR}/stream.m3u8"
HLS_SEGMENT_PATTERN = f"{STREAM_DIR}/stream%06d.ts"

LOG_FFMPEG = f"{LOG_DIR}/ffmpeg_engine.log"
LOG_PI = f"{LOG_DIR}/pi_engine.log"

STREAM_URL = f"http://{TAILSCALE_IP}:{HTTP_PORT}/stream.m3u8"

# ===================== STATE =====================
state = {
    "stream": False,
    "http_ok": False,
    "last_event": "boot",
    "last_error": "",
    "started_at": int(time.time()),
    "stream_started_at": 0.0,
    # Dodane dla kompatybilności z UI
    "motion_detection": False,
    "manual_record": False,
    "auto_record": False,
    "recording_active": False,
    "photos_taken": 0,
    "recordings_count": 0,
    "segments_generated": 0,
}

lock = threading.RLock()

proc = {
    "pi": None,
    "hls": None,
    "httpd": None,
    "http_thread": None,
}

log_ring = deque(maxlen=120)
_last_status_payload = None
_last_status_ts = 0.0
client = None

# ===================== COMMANDS =====================
# PI → RAW YUV420 to stdout
PI_CAM_PIPE_CMD = (
    "rpicam-vid -t 0 "
    "--codec yuv420 "
    "--width 640 --height 480 --framerate 30 "
    "--exposure normal --awb auto "
    "--gain 2.0 --brightness 0.3 "
    "-o -"
)

# SERVER → RAW YUV stdin → HLS LIVE
FFMPEG_FROM_STDIN_CMD = [
    "ffmpeg",
    "-hide_banner",
    "-loglevel", "info",
    "-use_wallclock_as_timestamps", "1",
    "-f", "rawvideo",
    "-pix_fmt", "yuv420p",
    "-s", "640x480",
    "-r", "30",
    "-i", "pipe:0",
    "-c:v", "libx264",
    "-preset", "veryfast",
    "-tune", "zerolatency",
    "-pix_fmt", "yuv420p",
    "-g", "30",
    "-keyint_min", "30",
    "-sc_threshold", "0",
    "-an",
    "-f", "hls",
    "-hls_time", "2",
    "-hls_list_size", "5",
    "-hls_segment_filename", HLS_SEGMENT_PATTERN,
    "-hls_flags", "delete_segments+independent_segments+omit_endlist",
    HLS_PLAYLIST,
]

# ===================== HELPERS =====================
def _publish(topic, payload, retain=False):
    if client:
        try:
            client.publish(topic, payload, retain=retain)
        except Exception:
            pass

def log(msg):
    msg = str(msg)
    print(msg, flush=True)
    log_ring.append(msg)
    _publish(T_LOG, msg)

def publish_status(event=None, err=None, force=False):
    global _last_status_payload, _last_status_ts
    
    if event:
        state["last_event"] = event
    if err is not None:
        state["last_error"] = err
    
    payload = json.dumps(state, ensure_ascii=False)
    now = time.time()
    
    if not force and payload == _last_status_payload and now - _last_status_ts < 1:
        return
    
    _last_status_payload = payload
    _last_status_ts = now
    _publish(T_STATUS, payload, retain=True)

def ack(cmd, ok, msg):
    _publish(
        T_ACK,
        json.dumps({
            "cmd": cmd,
            "result": "OK" if ok else "ERROR",
            "msg": msg,
            "ts": int(time.time()),
        }, ensure_ascii=False)
    )

def ensure_dirs():
    os.makedirs(STREAM_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

def clear_hls():
    subprocess.run(f"rm -f {STREAM_DIR}/*.ts {HLS_PLAYLIST}*", shell=True)

def stop_remote_pi():
    subprocess.run(
        f"ssh -o ConnectTimeout=3 {PI_HOST} 'pkill -9 -f rpicam-vid || true'",
        shell=True
    )

def stop_proc(k):
    p = proc.get(k)
    if p:
        try:
            p.terminate()
        except Exception:
            pass
    proc[k] = None

def cleanup(reason, err=""):
    stop_proc("hls")
    stop_proc("pi")
    stop_remote_pi()
    
    try:
        if proc["httpd"]:
            proc["httpd"].shutdown()
            proc["httpd"].server_close()
    except Exception:
        pass
    
    proc["httpd"] = None
    proc["http_thread"] = None
    
    state["stream"] = False
    state["http_ok"] = False
    publish_status(reason, err, force=True)

def hls_ready():
    return os.path.isfile(HLS_PLAYLIST) and os.path.getsize(HLS_PLAYLIST) > 0

# ===================== BRAKUJĄCE FUNKCJE =====================
def take_photo():
    """Zrób zdjęcie przez SSH na Pi"""
    try:
        log("Taking photo...")
        
        # Generuj unikalną nazwę pliku
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"photo_{timestamp}.jpg"
        remote_path = f"/tmp/{filename}"
        local_path = f"{BASE_DIR}/photos/{filename}"
        
        # Utwórz katalog na zdjęcia jeśli nie istnieje
        os.makedirs(f"{BASE_DIR}/photos", exist_ok=True)
        
        # Komenda robienia zdjęcia na Pi
        photo_cmd = (
            f"rpicam-jpeg -t 1 --width 1920 --height 1080 "
            f"--quality 95 --exposure normal --awb auto -o {remote_path}"
        )
        
        # Wykonaj przez SSH
        ssh_cmd = f"ssh -o ConnectTimeout=5 {PI_HOST} '{photo_cmd}'"
        result = subprocess.run(ssh_cmd, shell=True, capture_output=True, timeout=10)
        
        if result.returncode != 0:
            log(f"Photo failed on Pi: {result.stderr.decode()}")
            ack("photo", False, "Pi camera error")
            return False
        
        # Skopiuj zdjęcie lokalnie
        scp_cmd = f"scp {PI_HOST}:{remote_path} {local_path}"
        subprocess.run(scp_cmd, shell=True, capture_output=True, timeout=10)
        
        # Wyczyść na Pi
        subprocess.run(f"ssh {PI_HOST} 'rm -f {remote_path}'", shell=True)
        
        # Aktualizuj statystyki
        with lock:
            state["photos_taken"] += 1
        
        log(f"Photo saved: {filename}")
        ack("photo", True, f"Saved as {filename}")
        return True
        
    except subprocess.TimeoutExpired:
        ack("photo", False, "Timeout")
        return False
    except Exception as e:
        ack("photo", False, str(e))
        return False

def start_recording():
    """Rozpocznij nagrywanie manualne"""
    try:
        log("Starting recording...")
        
        # Generuj nazwę pliku
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"recording_{timestamp}.mp4"
        output_path = f"{BASE_DIR}/recordings/{filename}"
        
        # Utwórz katalog na nagrania
        os.makedirs(f"{BASE_DIR}/recordings", exist_ok=True)
        
        # Nagrywanie z HLS stream (nagrywa maksymalnie 1 godzinę)
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "info",
            "-t", "3600",  # Maksymalnie 1 godzina
            "-i", STREAM_URL,
            "-c", "copy",
            "-f", "mp4",
            output_path
        ]
        
        # Uruchom nagrywanie w tle
        proc["recording"] = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        
        # Aktualizuj stan
        with lock:
            state["manual_record"] = True
            state["recording_active"] = True
            state["recordings_count"] += 1
        
        log(f"Recording to: {filename}")
        ack("rec_on", True, f"Recording to {filename}")
        return True
        
    except Exception as e:
        ack("rec_on", False, str(e))
        return False

def stop_recording():
    """Zatrzymaj nagrywanie manualne"""
    try:
        log("Stopping recording...")
        
        if "recording" in proc and proc["recording"]:
            proc["recording"].terminate()
            time.sleep(0.5)
            if proc["recording"].poll() is None:
                proc["recording"].kill()
        
        # Aktualizuj stan
        with lock:
            state["manual_record"] = False
            state["recording_active"] = False
        
        log("Recording stopped")
        ack("rec_off", True, "Recording stopped")
        return True
        
    except Exception as e:
        ack("rec_off", False, str(e))
        return False

def generate_diagnostics():
    """Generuj tekst diagnostyki"""
    try:
        diag_lines = []
        diag_lines.append("=== STREAM DIAGNOSTICS ===")
        diag_lines.append(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        diag_lines.append(f"Stream active: {state['stream']}")
        diag_lines.append(f"HTTP server: {state['http_ok']}")
        diag_lines.append(f"Uptime: {int(time.time() - state['started_at'])}s")
        
        if state['stream']:
            stream_uptime = time.time() - state.get('stream_started_at', 0)
            diag_lines.append(f"Stream uptime: {int(stream_uptime)}s")
        
        diag_lines.append(f"Photos taken: {state.get('photos_taken', 0)}")
        diag_lines.append(f"Recordings: {state.get('recordings_count', 0)}")
        diag_lines.append("")
        diag_lines.append("=== PATHS ===")
        diag_lines.append(f"Stream URL: {STREAM_URL}")
        diag_lines.append(f"HLS playlist: {HLS_PLAYLIST}")
        diag_lines.append(f"Logs: {LOG_DIR}")
        
        diag_text = "\n".join(diag_lines)
        _publish(T_DIAG, json.dumps({"text": diag_text}, ensure_ascii=False))
        ack("diag", True, "Diagnostics generated")
        
    except Exception as e:
        ack("diag", False, str(e))

# ===================== HTTP =====================
def _http_thread():
    os.chdir(STREAM_DIR)
    httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), SimpleHTTPRequestHandler)
    proc["httpd"] = httpd
    httpd.serve_forever()

# ===================== STREAM =====================
def start_stream():
    with lock:
        if state["stream"]:
            ack("stream_on", True, "already running")
            return
    
    ensure_dirs()
    clear_hls()
    stop_remote_pi()
    
    proc["http_thread"] = threading.Thread(target=_http_thread, daemon=True)
    proc["http_thread"].start()
    time.sleep(0.3)
    
    if not proc["httpd"]:
        cleanup("http_failed")
        ack("stream_on", False, "http_failed")
        return
    
    pi_log = open(LOG_PI, "ab", buffering=0)
    ff_log = open(LOG_FFMPEG, "ab", buffering=0)
    
    proc["pi"] = subprocess.Popen(
        ["ssh", PI_HOST, PI_CAM_PIPE_CMD],
        stdout=subprocess.PIPE,
        stderr=pi_log,
        bufsize=0,
    )
    
    proc["hls"] = subprocess.Popen(
        FFMPEG_FROM_STDIN_CMD,
        stdin=proc["pi"].stdout,
        stdout=ff_log,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )
    
    for _ in range(20):
        time.sleep(1)
        if hls_ready():
            break
    else:
        cleanup("hls_not_created")
        ack("stream_on", False, "HLS not created")
        return
    
    state["stream"] = True
    state["http_ok"] = True
    state["stream_started_at"] = time.time()
    
    publish_status("stream_on", force=True)
    ack("stream_on", True, STREAM_URL)

def stop_stream():
    cleanup("stream_off")
    ack("stream_off", True, "stopped")

# ===================== MQTT =====================
def on_connect(c, *_):
    c.subscribe(T_CMD)
    publish_status("mqtt_connected", force=True)

def on_message(c, _, msg):
    cmd = msg.payload.decode(errors="ignore").strip().lower()
    log(f"Command received: {cmd}")
    
    if cmd == "stream_on":
        start_stream()
    elif cmd == "stream_off":
        stop_stream()
    elif cmd == "status":
        publish_status("status_requested", force=True)
    elif cmd == "diag":
        generate_diagnostics()
    elif cmd == "photo":
        threading.Thread(target=take_photo, daemon=True).start()
    elif cmd == "motion_on":
        with lock:
            state["motion_detection"] = True
        publish_status("motion_on", force=True)
        ack("motion_on", True, "Motion detection enabled")
    elif cmd == "motion_off":
        with lock:
            state["motion_detection"] = False
        publish_status("motion_off", force=True)
        ack("motion_off", True, "Motion detection disabled")
    elif cmd == "rec_on":
        threading.Thread(target=start_recording, daemon=True).start()
    elif cmd == "rec_off":
        threading.Thread(target=stop_recording, daemon=True).start()
    elif cmd == "rec_motion_on":
        with lock:
            state["auto_record"] = True
        publish_status("rec_motion_on", force=True)
        ack("rec_motion_on", True, "Auto-recording on motion enabled")
    elif cmd == "rec_motion_off":
        with lock:
            state["auto_record"] = False
        publish_status("rec_motion_off", force=True)
        ack("rec_motion_off", True, "Auto-recording on motion disabled")
    else:
        ack(cmd, False, "unknown command")

# ===================== MAIN =====================
def main():
    global client
    ensure_dirs()
    
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_forever()

if __name__ == "__main__":
    main()
