#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# hal_stream_ui.py - UI zgodne ze STARĄ wersją ale z nową funkcjonalnością

import curses
import time
import signal
import json
import threading
import subprocess
from collections import deque

import paho.mqtt.client as mqtt

ENGINE_CMD = ["python3", "/home/hal/HALbridge/mqtt_stream_v2.py"]
ENGINE_PGREP = "mqtt_stream_v2.py"

# ================= KONFIG =================
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

BASE = "hal/stream"
T_CMD = f"{BASE}/cmd"
T_STATUS = f"{BASE}/status"
T_ACK = f"{BASE}/ack"
T_LOG = f"{BASE}/log"
T_DIAG = f"{BASE}/diag"
T_HEALTH = f"{BASE}/health"  # Dodane z nowej wersji
T_EVENT = f"{BASE}/event"    # Dodane z nowej wersji

TAILSCALE_IP = "100.80.82.126"
HTTP_PORT = 8081
STREAM_URL = f"http://{TAILSCALE_IP}:{HTTP_PORT}/stream.m3u8"

PHOTO_FLASH_SECONDS = 0.5

# ================= STAN ===================
state = {
    # tryby/akcje (z silnika) - jak w starej wersji
    "stream": False,
    "motion": False,               # motion -> photos
    "record_manual": False,        # recording manual
    "record_on_motion": False,     # motion -> recording
    "recording_active": False,

    # diagnostyka / info (z silnika)
    "mqtt_ok": False,
    "pi_ok": False,
    "http_ok": False,
    "engine_running": False,

    "last_event": "init",
    "last_diag": [],
    "last_photo_ts": 0.0,
    "last_diag_text": "",
    "last_ack": "",
    
    # Dodane z nowej wersji
    "photos_taken": 0,
    "recordings_count": 0,
    "segments_generated": 0,
    "stream_uptime": 0,
    "components": {
        "ssh": "unknown",
        "camera": "unknown",
        "ffmpeg": "unknown",
        "http": "unknown",
        "hls": "unknown",
        "mqtt": "unknown"
    }
}

lock = threading.RLock()
log_ring = deque(maxlen=50)

client = None
engine_proc = None

# ================= SILNIK (START/DETEKCJA) =================
def is_engine_running():
    try:
        out = subprocess.check_output(
            f"pgrep -f {ENGINE_PGREP} || true",
            shell=True
        ).decode().strip()
        return bool(out)
    except Exception:
        return False

def start_engine():
    global engine_proc
    if is_engine_running():
        return True

    try:
        engine_proc = subprocess.Popen(
            ENGINE_CMD,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        with lock:
            state["last_event"] = f"❌ Engine start error: {e}"
        return False

    for _ in range(50):
        time.sleep(0.1)
        if is_engine_running():
            return True

    with lock:
        state["last_event"] = "❌ Engine nie wstał (timeout)"
    return False

# ================= MQTT HELPERS =================
def _publish_cmd(cmd: str):
    global client
    if not client:
        return
    try:
        client.publish(T_CMD, cmd, retain=False)
    except Exception:
        pass

def run_diagnostics():
    _publish_cmd("status")
    _publish_cmd("diag")

# ================= MQTT CALLBACKS =================
def on_connect(c, userdata, flags, rc, properties=None):
    with lock:
        state["mqtt_ok"] = True
        state["components"]["mqtt"] = "healthy"
        state["last_event"] = "✅ MQTT connected"

    c.subscribe(T_STATUS)
    c.subscribe(T_DIAG)
    c.subscribe(T_ACK)
    c.subscribe(T_LOG)
    c.subscribe(T_HEALTH)   # Dodane z nowej wersji
    c.subscribe(T_EVENT)    # Dodane z nowej wersji

    # po połączeniu MQTT silnik JUŻ subskrybuje → można wysyłać komendy
    c.publish(T_CMD, "status", retain=False)
    c.publish(T_CMD, "diag", retain=False)
    c.publish(T_CMD, "stream_on", retain=False)

def on_disconnect(c, userdata, rc, properties=None):
    with lock:
        state["mqtt_ok"] = False
        state["components"]["mqtt"] = "failed"
        state["last_event"] = "⚠ MQTT disconnected"

def on_message(c, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore")
    
    with lock:
        if topic == T_STATUS:
            try:
                s = json.loads(payload)
                
                # Mapowanie z nowego formatu na stary
                state["stream"] = s.get("state") == "active"
                state["engine_running"] = True
                
                # Features mapping
                features = s.get("features", {})
                state["record_manual"] = features.get("manual_record", False)
                state["motion"] = features.get("motion_detection", False)
                state["record_on_motion"] = features.get("auto_record", False)
                
                # Stats
                stats = s.get("stats", {})
                state["segments_generated"] = stats.get("segments_generated", 0)
                state["stream_uptime"] = stats.get("duration", 0)
                
                # Component health
                health = s.get("health", {})
                for comp in ["ssh", "camera", "ffmpeg", "http", "hls"]:
                    if comp in health:
                        state["components"][comp] = health[comp]
                
                # Update specific flags
                state["pi_ok"] = state["components"].get("camera") == "healthy"
                state["http_ok"] = state["components"].get("http") == "healthy"
                
                # Last event
                le = s.get("last_event")
                if le:
                    state["last_event"] = le
                    
            except Exception:
                pass
                
        elif topic == T_HEALTH:
            try:
                data = json.loads(payload)
                health = data.get("health", {})
                
                # Update component status
                for comp in ["ssh_connection", "pi_camera", "ffmpeg", "http_server", "hls_output"]:
                    ui_key = comp.replace("_connection", "").replace("pi_", "").replace("_server", "").replace("_output", "")
                    if ui_key not in state["components"]:
                        ui_key = comp
                        
                    if comp in health:
                        status = health[comp]
                        state["components"][ui_key] = status
                        
                        # Update specific flags
                        if ui_key == "camera":
                            state["pi_ok"] = status == "healthy"
                        elif ui_key == "http":
                            state["http_ok"] = status == "healthy"
                            
            except Exception:
                pass
                
        elif topic == T_EVENT:
            try:
                data = json.loads(payload)
                event_type = data.get("type", "")
                details = data.get("details", {})
                
                if event_type == "photo_captured":
                    state["photos_taken"] += 1
                    state["last_photo_ts"] = time.time()
                    state["last_event"] = "📸 Photo saved"
                elif event_type == "recording_started":
                    state["recordings_count"] += 1
                    state["recording_active"] = True
                    state["last_event"] = "🎬 Recording started"
                elif event_type == "recording_stopped":
                    state["recording_active"] = False
                    state["last_event"] = "🎬 Recording stopped"
                elif event_type == "stream_started":
                    state["last_event"] = "📡 Stream started"
                elif event_type == "stream_stopped":
                    state["last_event"] = "📡 Stream stopped"
                elif event_type == "error":
                    state["last_event"] = f"❌ Error: {details.get('message', 'Unknown')[:30]}"
                elif event_type == "warning":
                    state["last_event"] = f"⚠ Warning: {details.get('message', 'Unknown')[:30]}"
                    
            except Exception:
                pass
                
        elif topic == T_DIAG:
            try:
                j = json.loads(payload)
                diag_text = j.get("text", "") if isinstance(j, dict) else ""
            except Exception:
                diag_text = payload

            state["last_diag_text"] = diag_text
            lines = [ln.rstrip() for ln in diag_text.splitlines() if ln.strip()]
            state["last_diag"] = lines[:80]
            
        elif topic == T_ACK:
            try:
                a = json.loads(payload)
                msg_txt = a.get("msg", "")
                res = a.get("result", "")
                cmd = a.get("cmd", "")
                state["last_ack"] = f"{cmd}: {res} {msg_txt}".strip()

                if cmd == "photo" and res == "OK":
                    state["last_event"] = "📸 Photo saved"
                    state["last_photo_ts"] = time.time()
                elif cmd == "rec_on" and res == "OK":
                    state["last_event"] = "🎬 Recording started"
                elif cmd == "rec_off" and res == "OK":
                    state["last_event"] = "🎬 Recording stopped"
                elif cmd in ("stream_on", "stream_off") and res == "OK":
                    state["last_event"] = "📡 Stream ON" if cmd == "stream_on" else "📡 Stream OFF"
                    if cmd == "stream_on":
                        _publish_cmd("diag")
                elif cmd == "motion_on" and res == "OK":
                    state["last_event"] = "🧠 Motion detect ON"
                elif cmd == "motion_off" and res == "OK":
                    state["last_event"] = "🧠 Motion detect OFF"
                elif cmd == "rec_motion_on" and res == "OK":
                    state["last_event"] = "🧠 Motion → recording ON"
                elif cmd == "rec_motion_off" and res == "OK":
                    state["last_event"] = "🧠 Motion → recording OFF"
                elif msg_txt:
                    state["last_event"] = msg_txt
            except Exception:
                state["last_ack"] = payload

        elif topic == T_LOG:
            log_ring.append(payload.strip()[:200])

# ================= MQTT START/STOP =================
def mqtt_start():
    global client
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT)
    client.loop_start()

def mqtt_stop():
    global client
    try:
        if client:
            client.loop_stop()
            client.disconnect()
    except Exception:
        pass
    client = None

# ================= UI HELPERS =================
def safe_addstr(stdscr, y, x, text, color=0):
    h, w = stdscr.getmaxyx()
    if y < 0 or y >= h:
        return
    if x < 0:
        x = 0
    if x >= w:
        return
    try:
        stdscr.addstr(y, x, text[: max(0, w - x - 1)], color)
    except Exception:
        pass

def lamp(v, c_on, c_off):
    """Czerwone/zielone lampki jak w starym UI"""
    # Używamy czerwonego dla OFF i zielonego dla ON
    if v:
        return ("🔴", c_on)  # Czerwona gdy aktywny
    else:
        return ("⚪", c_off)  # Biała gdy nieaktywny

def draw_control_row(stdscr, y, lamp_char, lamp_color, icon, key, name, value, c_info, c_val):
    """Rysuj wiersz kontrolny ze starą stylistyką"""
    safe_addstr(stdscr, y, 2, lamp_char, lamp_color)  # Lampa na pozycji 2
    safe_addstr(stdscr, y, 6, icon, c_info)           # Ikona na pozycji 6
    safe_addstr(stdscr, y, 10, f"[{key}]", c_info)    # Klawisz [1] na pozycji 10
    safe_addstr(stdscr, y, 15, f"{name:<20}", c_info) # Nazwa na pozycji 15
    safe_addstr(stdscr, y, 37, ":", c_info)           # Dwukropek
    safe_addstr(stdscr, y, 40, value, c_val)          # Wartość

def draw_compact_diag(stdscr, y, key, name, status, status_color, c_info):
    """Rysuj kompaktową linię diagnostyki"""
    safe_addstr(stdscr, y, 2, f"[{key}]", c_info)
    safe_addstr(stdscr, y, 7, f"{name}", c_info)
    safe_addstr(stdscr, y, 25, f"{status}", status_color)

def build_diagnostics_text():
    """Buduj tekst diagnostyki jak w starym UI"""
    diag_lines = []
    
    # URL
    diag_lines.append("- URL: http://100.80.82.126:8081/stream.m3u8")
    
    # [0] Procesy
    diag_lines.append("- [0] Procesy")
    if state["engine_running"]:
        diag_lines.append("- SILNIK: DZIAŁA")
    else:
        diag_lines.append("- (brak)")
    
    # [1] Porty
    diag_lines.append("- [1] Porty")
    if state["http_ok"]:
        diag_lines.append(f"- LISTEN {HTTP_PORT}")
    else:
        diag_lines.append("- LISTEN 0")
    
    # [2] Pi camera
    diag_lines.append("- [2] Pi camera")
    diag_lines.append("- /usr/bin/rpicam-vid")
    diag_lines.append(f"- {'OK' if state['pi_ok'] else 'BRAK'}")
    
    # [3] HTTP HLS
    diag_lines.append("- [3] HTTP HLS")
    if state["http_ok"]:
        diag_lines.append("- #EXTM3U")
        diag_lines.append("- #EXT-X-VERSION:6")
    else:
        diag_lines.append("- (brak)")
    
    return diag_lines

def draw(stdscr):
    stdscr.clear()
    curses.start_color()
    
    # Kolory jak w starym UI
    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)   # Zielony - OK/ON
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)   # Biały - OFF/normalny
    curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)    # Cyjan - INFO
    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # Żółty - MENU/AKCJE
    curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)     # Czerwony - WARN/ERROR
    
    C_OK = curses.color_pair(1)      # Zielony
    C_OFF = curses.color_pair(2)     # Biały
    C_INFO = curses.color_pair(3)    # Cyjan
    C_MENU = curses.color_pair(4)    # Żółty
    C_WARN = curses.color_pair(5)    # Czerwony

    with lock:
        y = 1
        
        # ===== NAGŁÓWEK - STREAM URL =====
        safe_addstr(stdscr, y, 0, "STREAM URL", C_INFO)
        y += 1
        safe_addstr(stdscr, y, 0, STREAM_URL, C_OK)
        y += 2
        
        # ===== STEROWANIE - TRYB PRACY =====
        safe_addstr(stdscr, y, 0, "STEROWANIE - TRYB PRACY", C_MENU)
        y += 1
        
        # [1] Stream - lampa CZERWONA gdy ON, BIAŁA gdy OFF
        l, lc = lamp(state["stream"], C_WARN, C_OFF)  # Czerwony dla ON, biały dla OFF
        status = "[ON ]" if state["stream"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🎥", "1", "Stream", status, C_MENU, lc)
        y += 1
        
        # [2] Take photo - specjalna obsługa migania
        flash = (time.time() - state["last_photo_ts"]) < PHOTO_FLASH_SECONDS
        l, lc = lamp(flash, C_WARN, C_OFF)  # Czerwony podczas flash
        photo_status = "[FLASH]" if flash else "[    ]"
        draw_control_row(stdscr, y, l, lc, "📸", "2", "Take photo", photo_status, C_MENU, 
                        C_WARN if flash else C_OFF)
        y += 1
        
        # [3] Motion detect - photos (5)
        l, lc = lamp(state["motion"], C_WARN, C_OFF)
        status = "[ON ]" if state["motion"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "👁", "3", "Motion detect - photos (5)", 
                        status, C_MENU, lc)
        y += 1
        
        # [4] Recording (manual)
        l, lc = lamp(state["record_manual"], C_WARN, C_OFF)
        status = "[ON ]" if state["record_manual"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🎬", "4", "Recording (manual)", 
                        status, C_MENU, lc)
        y += 1
        
        # [5] Motion detect - recording
        l, lc = lamp(state["record_on_motion"], C_WARN, C_OFF)
        status = "[ON ]" if state["record_on_motion"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🧠", "5", "Motion detect - recording", 
                        status, C_MENU, lc)
        y += 2
        
        # ===== QUIT =====
        safe_addstr(stdscr, y, 0, "[q] Quit (graceful)", C_MENU)
        y += 2
        
        # ===== OSTATNIE ZDARZENIE =====
        safe_addstr(stdscr, y, 0, "Ostatnie zdarzenie:", C_INFO)
        y += 1
        safe_addstr(stdscr, y, 0, state["last_event"], C_OFF)
        y += 2
        
        # ===== DIAGNOSTYKA =====
        safe_addstr(stdscr, y, 0, "DIAGNOSTYKA (z silnika mqtt_stream_v2.py)", C_INFO)
        y += 1
        safe_addstr(stdscr, y, 0, "-- == STREAM DIAGNOSTYKA ===", C_INFO)
        y += 1
        
        # Wyświetl diagnostykę w starym stylu
        diag_lines = build_diagnostics_text()
        for line in diag_lines[:12]:  # Ogranicz do 12 linii
            safe_addstr(stdscr, y, 0, line, C_INFO)
            y += 1
        
        # Dodatkowe informacje
        y += 1
        mqtt_status = "OK" if state["mqtt_ok"] else "BRAK"
        mqtt_color = C_OK if state["mqtt_ok"] else C_WARN
        safe_addstr(stdscr, y, 0, f"MQTT: {mqtt_status}", mqtt_color)
        
        if state["stream"]:
            uptime_str = time.strftime("%H:%M:%S", time.gmtime(state["stream_uptime"]))
            safe_addstr(stdscr, y, 15, f"UPTIME: {uptime_str}", C_INFO)
            safe_addstr(stdscr, y, 35, f"SEGMENTS: {state['segments_generated']}", C_INFO)
            y += 1
        
        # Statystyki na dole
        stats_line = f"Photos: {state['photos_taken']} | Recordings: {state['recordings_count']}"
        safe_addstr(stdscr, y, 0, stats_line, C_INFO)
        y += 1
        
        # Stopka z klawiszami (opcjonalnie)
        h, w = stdscr.getmaxyx()
        if h - y >= 3:
            y = h - 3
            safe_addstr(stdscr, y, 0, "ESC    /    --    HOME    ↑    END    PGUP", C_OFF)
            y += 1
            safe_addstr(stdscr, y, 4, "CTRL    ALT    --    ↓    →    PGDN", C_OFF)

    stdscr.refresh()

# ================= UI LOOP =================
def ui(stdscr):
    curses.curs_set(0)
    stdscr.timeout(100)

    start_engine()
    mqtt_start()

    time.sleep(0.2)
    run_diagnostics()

    with lock:
        state["last_event"] = "✅ UI uruchomione, wysyłam stream_on"

    last_poll = 0.0

    while True:
        now = time.time()
        
        # Automatyczne odświeżanie diagnostyki co 2 sekundy
        if now - last_poll > 2.0:
            run_diagnostics()
            last_poll = now

        draw(stdscr)

        k = stdscr.getch()
        if k == -1:
            continue

        if k == ord('q'):
            run_diagnostics()
            mqtt_stop()
            break

        if k == ord('1'):
            with lock:
                want_off = state["stream"]
            _publish_cmd("stream_off" if want_off else "stream_on")
            run_diagnostics()

        elif k == ord('2'):
            _publish_cmd("photo")
            run_diagnostics()

        elif k == ord('3'):
            with lock:
                want_off = state["motion"]
            _publish_cmd("motion_off" if want_off else "motion_on")
            run_diagnostics()

        elif k == ord('4'):
            with lock:
                want_off = state["record_manual"]
            _publish_cmd("rec_off" if want_off else "rec_on")
            run_diagnostics()

        elif k == ord('5'):
            with lock:
                want_off = state["record_on_motion"]
            _publish_cmd("rec_motion_off" if want_off else "rec_motion_on")
            run_diagnostics()

# ================= MAIN ===================
def _sig_handler(*_):
    raise SystemExit(0)

def main():
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    curses.wrapper(ui)

if __name__ == "__main__":
    main()
