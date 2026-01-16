#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import subprocess
import time
import signal
import sys
import shlex
import os
import json
import threading
import traceback
import http.server
import socketserver
from collections import deque
import paho.mqtt.client as mqtt
def _require_systemd():
    # systemd ustawia tę zmienną automatycznie
    if os.getenv("INVOCATION_ID") is None:
        print("❌ Ten program może być uruchamiany wyłącznie przez systemd (hal-stream.service)")
        sys.exit(1)
_require_systemd()

# MQTT
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883
BASE = "hal/stream"
T_CMD = f"{BASE}/cmd"
T_STATUS = f"{BASE}/status"
T_ACK = f"{BASE}/ack"
T_LOG = f"{BASE}/log"
T_DIAG = f"{BASE}/diag"
T_HELP_GET = f"{BASE}/help/get"
T_HELP_RESP = f"{BASE}/help/response"
T_CAPS = f"{BASE}/capabilities"
T_COMMANDS = f"{BASE}/commands"
# SYSTEM
PI_HOST = "zero@192.168.100.16"
SERVER_IP = "192.168.100.12"
TAILSCALE_IP = "100.80.82.126"
HTTP_PORT = 8081
TCP_PORT = 8554
BASE_DIR = "/home/hal/HALbridge/media"
STREAM_DIR = f"{BASE_DIR}/stream"
HLS_PLAYLIST = f"{STREAM_DIR}/stream.m3u8"
SNAPSHOT_DIR = f"{BASE_DIR}/snapshots"
MOTION_DIR = f"{BASE_DIR}/motion"
RECORD_DIR = f"{BASE_DIR}/recordings"
SNAP_INTERVAL = 5
MOTION_THRESHOLD = 0.02
MOTION_HOLD_TIME = 10
STREAM_URL = f"http://{TAILSCALE_IP}:{HTTP_PORT}/stream.m3u8"

# STATE
state = {
    "stream": False,
    "snapshots": False,
    "motion": False,              # motion -> photos
    "record_manual": False,
    "record_on_motion": False,
    "recording_active": False,
    "http_ok": False,
    "last_event": "boot",
    "last_error": "",
    "started_at": int(time.time()),
}

lock = threading.RLock()

proc = {
    "hls": None,          # ffmpeg HLS muxer
    "pi": None,           # ssh rpicam-vid
    "motion": None,
    "rec": None,
    "httpd": None,        # HTTPServer instance
    "http_thread": None,  # HTTP server thread
}

known_motion_files = set()
last_motion_time = 0.0
log_ring = deque(maxlen=80)

# Throttle/status diff
_last_status_payload = None
_last_status_ts = 0.0

# COMMAND STRINGS
PI_CAM_CMD = (
    "rpicam-vid -t 0 --inline --profile baseline "
    "--width 640 --height 480 --bitrate 2000000 "
    "--intra 30 "
    f"-o tcp://{SERVER_IP}:{TCP_PORT}"
)

FFMPEG_HLS = (
    f"ffmpeg -loglevel error "
    f"-fflags nobuffer -flags low_delay "
    f"-f h264 -i tcp://0.0.0.0:{TCP_PORT}?listen=1 "
    f"-map 0:v:0 "
    f"-c:v libx264 "
    f"-preset ultrafast "
    f"-tune zerolatency "
    f"-profile:v baseline "
    f"-level 3.0 "
    f"-pix_fmt yuv420p "
    f"-g 30 -keyint_min 30 -sc_threshold 0 "
    f"-an "
    f"-f hls "
    f"-hls_time 2 "
    f"-hls_list_size 5 "
    f"-hls_flags delete_segments+append_list+independent_segments "
    f"{STREAM_DIR}/stream.m3u8"
)

# One-shot photo
PHOTO_CMD = (
    f"ffmpeg -hide_banner -loglevel error -y "
    f"-i http://127.0.0.1:{HTTP_PORT}/stream.m3u8 "
    f"-frames:v 1 -strftime 1 "
    f"{SNAPSHOT_DIR}/photo_%Y%m%d_%H%M%S.jpg"
)

# Motion detect -> photos
MOTION_CMD = (
    f"ffmpeg -hide_banner -loglevel error "
    f"-i http://127.0.0.1:{HTTP_PORT}/stream.m3u8 "
    f"-vf \"select=gt(scene\\,{MOTION_THRESHOLD})\" "
    f"-vsync vfr -strftime 1 "
    f"{MOTION_DIR}/motion_%Y%m%d_%H%M%S.jpg"
)

# Recording
REC_CMD = (
    f"ffmpeg -hide_banner -loglevel error "
    f"-i http://127.0.0.1:{HTTP_PORT}/stream.m3u8 "
    f"-c copy -strftime 1 "
    f"{RECORD_DIR}/rec_%Y%m%d_%H%M%S.mp4"
)

# MQTT HELPERS
client = None

def _publish(topic, payload, retain=False):
    if not client:
        return
    try:
        client.publish(topic, payload, retain=retain)
    except Exception:
        pass

def log(msg):
    msg = str(msg)
    print(msg, flush=True)
    log_ring.append(msg)
    _publish(T_LOG, msg, retain=False)

def _status_payload():
    return json.dumps(state, ensure_ascii=False)

def publish_status(event=None, err=None, force=False):
    global _last_status_payload, _last_status_ts
    if event:
        state["last_event"] = event
    if err is not None:
        state["last_error"] = err
    now = time.time()
    payload = _status_payload()
    # Throttle: max 1/s unless force or payload changed
    if not force:
        if payload == _last_status_payload and (now - _last_status_ts) < 1.0:
            return
        if (now - _last_status_ts) < 1.0 and payload == _last_status_payload:
            return

    _last_status_payload = payload
    _last_status_ts = now
    _publish(T_STATUS, payload, retain=True)

def ack(cmd, ok, msg):
    payload = {
        "cmd": cmd,
        "result": "OK" if ok else "ERROR",
        "msg": msg,
        "state": state,
        "ts": int(time.time()),
    }
    _publish(T_ACK, json.dumps(payload, ensure_ascii=False), retain=False)

def publish_diag(text):
    payload = {
        "ts": int(time.time()),
        "text": text,
    }
    _publish(T_DIAG, json.dumps(payload, ensure_ascii=False), retain=True)

def hls_is_ready():
    try:
        if not os.path.isfile(HLS_PLAYLIST):
            return False
        with open(HLS_PLAYLIST, "r") as f:
            data = f.read()

        if os.path.getsize(HLS_PLAYLIST) > 0:
            return True

        lines = [l.strip() for l in data.splitlines() if l.strip()]
        return len(lines) >= 3
    except Exception:
        return False

def http_is_healthy():
    try:
        r = subprocess.run(
            ["curl", "-sf", "--max-time", "1", f"http://127.0.0.1:{HTTP_PORT}/stream.m3u8"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return r.returncode == 0
    except Exception:
        return False
# LOW-LEVEL UTILS
def sh(cmd):
    return subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def ensure_dirs():
    for d in [STREAM_DIR, SNAPSHOT_DIR, MOTION_DIR, RECORD_DIR]:
        os.makedirs(d, exist_ok=True)

def clear_hls_files():
    print("AFTER clear_hls_files")
    sh(f"rm -f {STREAM_DIR}/*.ts {STREAM_DIR}/stream.m3u8 {STREAM_DIR}/stream.m3u8.tmp || true")

def is_alive(p):
    return (p is not None) and (p.poll() is None)

def stop_proc(key, wait=1.0):
    p = proc.get(key)
    if p is None:
        return
    try:
        p.terminate()
        try:
            p.wait(timeout=wait)
        except Exception:
            pass
    except Exception:
        pass
    proc[key] = None

def stop_remote_pi_cam():
    # Kill rpicam-vid on Pi, regardless of local ssh state
    sh(f"ssh -o ConnectTimeout=3 {PI_HOST} 'pkill -TERM -f rpicam-vid || true' || true")
    time.sleep(0.2)
    sh(f"ssh -o ConnectTimeout=3 {PI_HOST} 'pkill -KILL -f rpicam-vid || true' || true")

def kill_sweep_project_only():
    # - ffmpeg processes that touch our stream dir or listen TCP_PORT
    sh(f"pkill -TERM -f \"ffmpeg .*{STREAM_DIR}\" || true")
    sh(f"pkill -TERM -f \"tcp://0.0.0.0:{TCP_PORT}\\?listen=1\" || true")
    sh(f"pkill -TERM -f \"http.server {HTTP_PORT}\" || true")
    sh(f"pkill -TERM -f \"ssh .*{PI_HOST}.*rpicam-vid\" || true")
    time.sleep(0.4)
    sh(f"pkill -KILL -f \"ffmpeg .*{STREAM_DIR}\" || true")
    sh(f"pkill -KILL -f \"tcp://0.0.0.0:{TCP_PORT}\\?listen=1\" || true")
    sh(f"pkill -KILL -f \"http.server {HTTP_PORT}\" || true")
    sh(f"pkill -KILL -f \"ssh .*{PI_HOST}.*rpicam-vid\" || true")

def _cleanup_all(reason="cleanup"):
    # Stop local procs
    for k in list(proc.keys()):
        stop_proc(k)
    # Stop remote cam
    stop_remote_pi_cam()
    # Clear flags
    state["stream"] = False
    state["motion"] = False
    state["record_manual"] = False
    state["record_on_motion"] = False
    state["recording_active"] = False
    # stop embedded HTTP server (threaded)
    try:
        httpd = proc.get("httpd")
        if httpd:
            httpd.shutdown()
            httpd.server_close()
    except Exception:
        pass
    finally:
        proc["httpd"] = None
        proc["http_thread"] = None
    publish_status(reason, force=True)

# DIAGNOSTYKA
def run_diagnostics():
    ensure_dirs()
    lines = []
    lines.append("=== STREAM DIAGNOSTYKA ===")
    lines.append(f"URL: {STREAM_URL}")
    lines.append("")

    r = sh("ps aux | egrep 'ffmpeg|rpicam|http.server|ssh .*rpicam-vid' | grep -v grep || true")
    lines.append("[0] Procesy")
    lines.append((r.stdout or "").strip() or "(brak)")
    lines.append("")

    r = sh(f"ss -ltnp | egrep ':{TCP_PORT}|:{HTTP_PORT}' || true")
    lines.append("[1] Porty")
    lines.append((r.stdout or "").strip() or "(brak)")
    lines.append("")

    r = sh(f"ssh -o ConnectTimeout=3 -o BatchMode=yes {PI_HOST} 'command -v rpicam-vid && echo OK' || true")
    lines.append("[2] Pi camera")
    lines.append((r.stdout or "").strip() or "(brak)")
    lines.append("")

    r = sh(f"curl -m 2 -s http://127.0.0.1:{HTTP_PORT}/stream.m3u8 | head -n 8 || true")
    lines.append("[3] HTTP HLS")
    lines.append((r.stdout or "").strip() or "(brak)")

    diag = "\n".join(lines)
    publish_diag(diag)
    return diag

# STREAM ACTIONS
def wait_port(port, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            out = subprocess.check_output(["ss", "-ltn"], text=True)
            if f":{port} " in out:
                return True
        except Exception:
            pass
        time.sleep(0.1)
    return False

from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

def start_http_server():
    try:
        os.chdir(STREAM_DIR)
        httpd = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), SimpleHTTPRequestHandler)
        proc["httpd"] = httpd
        httpd.serve_forever()
    except Exception as e:
        log(f"[http] server crashed: {e}")

def start_stream():
    print("ENTER start_stream")
    with lock:
        if state.get("stream"):
            ack("stream_on", True, "Streaming już działa")
            return

        ensure_dirs()
        clear_hls_files()
        stop_remote_pi_cam()

        # helper: wait for file existence
        def wait_file(path, timeout=10.0):
            t0 = time.time()
            while time.time() - t0 < timeout:
                if os.path.exists(path) and os.path.getsize(path) > 0:
                    return True
                time.sleep(0.1)
            return False

        # helper: wait until ffmpeg listens on TCP
        def wait_port_listen(port, timeout=5.0):
            t0 = time.time()
            while time.time() - t0 < timeout:
                try:
                    out = subprocess.check_output(["ss", "-ltn"], text=True)
                    if f":{port} " in out:
                        return True
                except Exception:
                    pass
                time.sleep(0.1)
            return False

        # 1) start ffmpeg (HLS muxer)
        print("BEFORE FFMPEG")
        proc["hls"] = subprocess.Popen(
            shlex.split(FFMPEG_HLS),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("AFTER FFMPEG")

        if not wait_port_listen(TCP_PORT, timeout=5.0):
            _cleanup_all("ffmpeg_not_listening")
            ack("stream_on", False, f"ffmpeg_not_listening:{TCP_PORT}")
            return

        # 2) start Pi camera push
        print("BEFORE PI SSH")
        proc["pi"] = subprocess.Popen(
            f"ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=no {PI_HOST} '{PI_CAM_CMD}'",
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        print("AFTER PI SSH")

        # 3) wait for HLS playlist
        if not wait_file(HLS_PLAYLIST, timeout=10.0):
            _cleanup_all("hls_not_created")
            ack("stream_on", False, "HLS not created")
            return

        # 4) start HTTP server in-thread (NO subprocess)
        print("START HTTP THREAD")
        proc["http_thread"] = threading.Thread(
            target=start_http_server,
            daemon=True
        )
        proc["http_thread"].start()

        time.sleep(0.3)
        if not proc.get("httpd"):
            _cleanup_all("http_failed")
            ack("stream_on", False, "http_server_failed")
            return

        # 5) success
        print("HLS READY → STREAM ON")
        state["stream"] = True
        state["stream_started_at"] = time.time()
        publish_status("stream_on", force=True)
        ack("stream_on", True, STREAM_URL)

def stop_stream():
    with lock:
        _cleanup_all("stream_off")
        ack("stream_off", True, "stop")

# FEATURE ACTIONS (photo/motion/rec)
def take_photo_once():
    with lock:
        if not state["stream"]:
            ack("photo", False, "stream_off")
            return

    ensure_dirs()

    # Give HLS a moment if someone instantly spams photo after start
    for _ in range(10):
        if hls_is_ready():
            break
        time.sleep(0.1)

    r = subprocess.run(PHOTO_CMD, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if r.returncode == 0:
        ack("photo", True, "photo saved")
        publish_status("photo_saved")
    else:
        ack("photo", False, "photo failed")
        publish_status("photo_failed", err="photo_failed")

def _ensure_motion_proc():
    want = state["stream"] and (state["motion"] or state["record_on_motion"])
    if want:
        if not is_alive(proc.get("motion")):
            ensure_dirs()
            proc["motion"] = subprocess.Popen(MOTION_CMD, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        stop_proc("motion")

def _ensure_rec_proc(want_rec: bool):
    if want_rec and state["stream"]:
        if not is_alive(proc.get("rec")):
            ensure_dirs()
            proc["rec"] = subprocess.Popen(REC_CMD, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            state["recording_active"] = True
    else:
        if is_alive(proc.get("rec")):
            stop_proc("rec")
        state["recording_active"] = False

def _scan_motion_dir_update_ts():
    global last_motion_time, known_motion_files
    try:
        if not os.path.isdir(MOTION_DIR):
            return
        files = [f for f in os.listdir(MOTION_DIR) if f.startswith("motion_") and f.endswith(".jpg")]
        new = False
        for f in files:
            if f not in known_motion_files:
                known_motion_files.add(f)
                new = True
        if new:
            last_motion_time = time.time()

        # Prevent unbounded growth
        if len(known_motion_files) > 5000:
            known_motion_files = set(list(known_motion_files)[-1000:])
    except Exception:
        pass

def _watchdog_stream_health():
    # Watchdog: HLS + realny healthcheck HTTP
    if not state.get("stream"):
        return

    # grace period po starcie streamu
    if time.time() - state.get("stream_started_at", 0) < 6:
        return

    # 1) HLS (ffmpeg muxer) — KRYTYCZNY
    p = proc.get("hls")
    if p is None or not is_alive(p):
        state["last_error"] = "proc_dead:hls"
        _cleanup_all("stream_crashed")
        log("[watchdog] stream crashed, dead=hls")
        return

    # 2) HTTP — REALNY HEALTHCHECK (nie PID)
    state["http_ok"] = http_is_healthy()
    if not http_is_healthy():
        log("[watchdog] HTTP healthcheck FAILED, restarting http server")
        stop_proc("http")
        try:
            proc["http"] = subprocess.Popen(
                ["python3", "-m", "http.server", str(HTTP_PORT), "--bind", "0.0.0.0"],
                cwd=STREAM_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            log("[watchdog] HTTP server restarted")
        except Exception as e:
            state["last_error"] = f"http_restart_failed:{e}"
            log(f"[watchdog] HTTP restart failed: {e}")

def control_loop():
    global last_motion_time
    while True:
        time.sleep(0.25)
        with lock:
            try:
                _watchdog_stream_health()

                _ensure_motion_proc()
                _scan_motion_dir_update_ts()

                want_rec = False
                if state["record_manual"]:
                    want_rec = True
                elif state["record_on_motion"]:
                    if (time.time() - last_motion_time) < float(MOTION_HOLD_TIME):
                        want_rec = True

                _ensure_rec_proc(want_rec)

                publish_status()
            except Exception as e:
                state["last_error"] = str(e)
                publish_status(err=str(e))

# MQTT CALLBACKS
def on_connect(c, *_):
    c.subscribe(T_CMD)
    c.subscribe(T_HELP_GET)
    publish_status("mqtt_connected", force=True)
    run_diagnostics()

def on_message(c, _, msg):
    # DEBUG: pokaż KAŻDĄ przychodzącą wiadomość
    _publish(T_LOG, f"RAW CMD: {msg.payload!r}")

    try:
        cmd = msg.payload.decode("utf-8", errors="replace").strip().lower()
    except Exception as e:
        _publish(T_LOG, f"DECODE ERROR: {e}")
        return

    if cmd == "stream_on":
        start_stream()
    elif cmd == "stream_off":
        stop_stream()
    elif cmd == "diag":
        run_diagnostics()
    elif cmd == "status":
        publish_status("status", force=True)
    elif cmd == "photo":
        take_photo_once()
    elif cmd == "motion_on":
        with lock:
            state["motion"] = True
            state["record_on_motion"] = False
        publish_status("motion_on", force=True)
        ack("motion_on", True, "motion on")
    elif cmd == "motion_off":
        with lock:
            state["motion"] = False
        publish_status("motion_off", force=True)
        ack("motion_off", True, "motion off")
    elif cmd == "rec_on":
        with lock:
            state["record_manual"] = True
            state["record_on_motion"] = False
        publish_status("rec_on", force=True)
        ack("rec_on", True, "recording on")
    elif cmd == "rec_off":
        with lock:
            state["record_manual"] = False
        publish_status("rec_off", force=True)
        ack("rec_off", True, "recording off")
    elif cmd == "rec_motion_on":
        with lock:
            state["record_on_motion"] = True
            state["motion"] = False
            state["record_manual"] = False
        publish_status("rec_motion_on", force=True)
        ack("rec_motion_on", True, "motion→record on")
    elif cmd == "rec_motion_off":
        with lock:
            state["record_on_motion"] = False
        publish_status("rec_motion_off", force=True)
        ack("rec_motion_off", True, "motion→record off")
    else:
        ack(cmd, False, "unknown cmd")

# MAIN
def _sig_handler(*_):
    raise SystemExit(0)

def main():
    global client
    ensure_dirs()
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    th = threading.Thread(target=control_loop, daemon=True)
    th.start()
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_forever()

if __name__ == "__main__":
    main()
