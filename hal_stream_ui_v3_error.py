#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# hal_stream_ui.py - UI zgodne z nową wersją silnika mqtt_stream_v2.py

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
T_HEALTH = f"{BASE}/health"
T_EVENT = f"{BASE}/event"

TAILSCALE_IP = "100.80.82.126"
HTTP_PORT = 8081
STREAM_URL = f"http://{TAILSCALE_IP}:{HTTP_PORT}/stream.m3u8"

PHOTO_FLASH_SECONDS = 0.5

# ================= STAN ===================
state = {
    # tryby/akcje (z silnika) - ZMAPOWANE do nowych nazw
    "stream": False,
    "motion": False,  # motion -> photos (mapowane z motion_detection)
    "record_manual": False,  # recording manual (mapowane z manual_record)
    "record_on_motion": False,  # motion -> recording (mapowane z auto_record)
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
    },
    
    # Nowe flagi dla poprawionej logiki
    "command_pending": False,
    "last_response_time": time.time(),
    "stream_requested": False,
    "diagnostics_requested": False
}

lock = threading.RLock()
log_ring = deque(maxlen=50)

client = None
engine_proc = None
last_mqtt_message_time = 0

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
        return False
    
    with lock:
        state["command_pending"] = True
    
    try:
        client.publish(T_CMD, cmd, retain=False)
        return True
    except Exception:
        with lock:
            state["command_pending"] = False
        return False

def run_diagnostics():
    """Realna diagnostyka z oczekiwaniem na odpowiedź"""
    with lock:
        state["diagnostics_requested"] = True
        state["last_diag_text"] = "(wysyłam diagnostykę...)"
    
    # Wyślij komendy diagnostyczne
    sent1 = _publish_cmd("status")
    time.sleep(0.1)  # Mała przerwa między komendami
    sent2 = _publish_cmd("diag")
    
    if not (sent1 or sent2):
        with lock:
            state["diagnostics_requested"] = False
            state["last_diag_text"] = "(błąd wysyłania diagnostyki)"
    
    return sent1 or sent2

# ================= MQTT CALLBACKS =================
def on_connect(c, userdata, flags, rc, properties=None):
    global last_mqtt_message_time
    last_mqtt_message_time = time.time()
    
    with lock:
        state["mqtt_ok"] = True
        state["components"]["mqtt"] = "healthy"
        state["last_event"] = "✅ MQTT connected"
        state["last_response_time"] = time.time()
    
    c.subscribe(T_STATUS)
    c.subscribe(T_DIAG)
    c.subscribe(T_ACK)
    c.subscribe(T_LOG)
    c.subscribe(T_HEALTH)
    c.subscribe(T_EVENT)
    
    # NIGDY nie wysyłaj automatycznie stream_on!
    # Tylko poproś o aktualny status systemu
    
    time.sleep(0.3)
    c.publish(T_CMD, "status", retain=False)
    
    with lock:
        state["stream_requested"] = False
        state["last_event"] = "✅ Połączono - sprawdzam status..."

def on_disconnect(c, userdata, rc, properties=None):
    with lock:
        state["mqtt_ok"] = False
        state["components"]["mqtt"] = "failed"
        state["last_event"] = "⚠ MQTT disconnected"
        state["command_pending"] = False

def on_message(c, userdata, msg):
    global last_mqtt_message_time
    last_mqtt_message_time = time.time()
    
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore")
    
    with lock:
        state["last_response_time"] = time.time()
        state["command_pending"] = False

def on_disconnect(c, userdata, rc, properties=None):
    with lock:
        state["mqtt_ok"] = False
        state["components"]["mqtt"] = "failed"
        state["last_event"] = "⚠ MQTT disconnected"
        state["command_pending"] = False

def on_message(c, userdata, msg):
    global last_mqtt_message_time
    last_mqtt_message_time = time.time()
    
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore")
    
    with lock:
        state["last_response_time"] = time.time()
        state["command_pending"] = False
        
        if topic == T_STATUS:
            try:
                s = json.loads(payload)
                state["stream"] = s.get("stream", False)
                state["engine_running"] = True
                state["http_ok"] = s.get("http_ok", False)
                
                # Aktualizuj czas rozpoczęcia streamingu
                if state["stream"] and "stream_started_at" in s:
                    started = s["stream_started_at"]
                    if started > 0:
                        state["stream_uptime"] = time.time() - started
                
                # Parsowanie features (MAPOWANIE nazw!)
                features = s.get("features", {})
                state["motion"] = features.get("motion_detection", False)
                state["record_manual"] = features.get("manual_record", False)
                state["record_on_motion"] = features.get("auto_record", False)
                
                # Parsowanie stats
                stats = s.get("stats", {})
                state["photos_taken"] = stats.get("photos_taken", 0)
                state["recordings_count"] = stats.get("recordings_count", 0)
                state["segments_generated"] = stats.get("segments_generated", 0)
                if "duration" in stats:
                    state["stream_uptime"] = stats["duration"]
                
                # Parsowanie health/components
                health = s.get("health", {})
                if isinstance(health, dict):
                    state["components"] = health
                    state["pi_ok"] = health.get("pi_camera") == "healthy"
                
                # Ostatnie zdarzenie z silnika
                last_event = s.get("last_event", "")
                if last_event:
                    state["last_event"] = last_event
                    
            except Exception:
                pass
        
        elif topic == T_DIAG:
            state["diagnostics_requested"] = False
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
                
                if cmd == "stream_on" and res == "OK":
                    state["stream"] = True
                    state["last_event"] = "📡 Stream ON"
                    # Wymuś aktualizację statusu po włączeniu streamu
                    c.publish(T_CMD, "status", retain=False)
                elif cmd == "stream_off" and res == "OK":
                    state["stream"] = False
                    state["last_event"] = "📡 Stream OFF"
                elif cmd == "photo" and res == "OK":
                    state["last_event"] = "📸 Photo saved"
                    state["last_photo_ts"] = time.time()
                    state["photos_taken"] += 1
                elif cmd == "rec_on" and res == "OK":
                    state["last_event"] = "🎬 Recording started"
                    state["record_manual"] = True
                elif cmd == "rec_off" and res == "OK":
                    state["last_event"] = "🎬 Recording stopped"
                    state["record_manual"] = False
                elif cmd == "motion_on" and res == "OK":
                    state["last_event"] = "🧠 Motion detect ON"
                    state["motion"] = True
                elif cmd == "motion_off" and res == "OK":
                    state["last_event"] = "🧠 Motion detect OFF"
                    state["motion"] = False
                elif cmd == "rec_motion_on" and res == "OK":
                    state["last_event"] = "🧠 Motion → recording ON"
                    state["record_on_motion"] = True
                elif cmd == "rec_motion_off" and res == "OK":
                    state["last_event"] = "🧠 Motion → recording OFF"
                    state["record_on_motion"] = False
                elif msg_txt:
                    state["last_event"] = msg_txt
                    
            except Exception:
                state["last_ack"] = payload
                state["last_event"] = f"ACK: {payload[:30]}"
        
        elif topic == T_LOG:
            log_ring.append(payload.strip()[:200])
        
        elif topic == T_HEALTH:
            try:
                h = json.loads(payload)
                health_data = h.get("health", {})
                if isinstance(health_data, dict):
                    state["components"] = health_data
                    state["pi_ok"] = health_data.get("pi_camera") == "healthy"
            except Exception:
                pass
        
        elif topic == T_EVENT:
            try:
                e = json.loads(payload)
                event_type = e.get("type", "")
                if event_type == "photo_captured":
                    state["photos_taken"] = e.get("details", {}).get("counter", state["photos_taken"])
                elif event_type == "recording_started":
                    state["recordings_count"] += 1
            except Exception:
                pass

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

def lamp(v):
    """Zwraca (ikona, kolor) - zielony=ON, czerwony=OFF"""
    if v:
        return ("🟢", curses.color_pair(1))  # Zielony dla ON
    else:
        return ("🔴", curses.color_pair(5))  # Czerwony dla OFF

def draw_control_row(stdscr, y, lamp_char, lamp_color, icon, key, name, value, c_info, c_val):
    """Rysuj wiersz kontrolny ze starą stylistyką"""
    safe_addstr(stdscr, y, 2, lamp_char, lamp_color)  # Lampa na pozycji 2
    safe_addstr(stdscr, y, 6, icon, c_info)           # Ikona na pozycji 6
    safe_addstr(stdscr, y, 10, f"[{key}]", c_info)    # Klawisz [1] na pozycji 10
    safe_addstr(stdscr, y, 15, f"{name:<20}", c_info) # Nazwa na pozycji 15
    safe_addstr(stdscr, y, 37, ":", c_info)           # Dwukropek
    safe_addstr(stdscr, y, 40, value, c_val)          # Wartość

def build_diagnostics_text():
    """Buduj tekst diagnostyki jak w starym UI"""
    diag_lines = []
    
    # URL
    diag_lines.append(f"- URL: {STREAM_URL}")
    
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

def check_engine_health():
    """Sprawdź czy silnik odpowiada"""
    global last_mqtt_message_time
    
    with lock:
        now = time.time()
        time_since_last_msg = now - last_mqtt_message_time
        
        # Jeśli nie było odpowiedzi przez 10 sekund i MQTT jest OK
        if time_since_last_msg > 10.0 and state["mqtt_ok"]:
            # Sprawdź czy proces jeszcze żyje
            engine_alive = is_engine_running()
            state["engine_running"] = engine_alive
            
            if not engine_alive:
                state["last_event"] = "❌ Silnik nie odpowiada (zmarł)"
                state["mqtt_ok"] = False
                state["components"]["mqtt"] = "failed"
            elif state["command_pending"] and time_since_last_msg > 5.0:
                state["last_event"] = "⚠ Brak odpowiedzi na komendę"
                state["command_pending"] = False

def ensure_streaming_on():
    """NIE włączaj automatycznie - tylko informuj o możliwości"""
    with lock:
        # Tylko informacja, nie akcja
        if not state["stream"] and not state["command_pending"]:
            state["last_event"] = "Stream OFF - naciśnij [1] aby włączyć"
    return False  # Zawsze zwracaj False - nie włączaj automatycznie

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
        safe_addstr(stdscr, y, 0, STREAM_URL, C_OK if state["stream"] else C_OFF)
        y += 2
        
        # ===== STEROWANIE - TRYB PRACY =====
        safe_addstr(stdscr, y, 0, "STEROWANIE - TRYB PRACY", C_MENU)
        y += 1
        
        # [1] Stream - zielony gdy ON, czerwony gdy OFF
        l, lc = lamp(state["stream"])
        status = "[ON ]" if state["stream"] else "[OFF]"
        if state["command_pending"] and not state["stream"] and state["stream_requested"]:
            status = "[...]"
            l, lc = ("🟡", C_WARN)  # Żółty podczas oczekiwania
        draw_control_row(stdscr, y, l, lc, "🎥", "1", "Stream", status, C_MENU, lc)
        y += 1
        
        # [2] Take photo - specjalna obsługa migania
        flash = (time.time() - state["last_photo_ts"]) < PHOTO_FLASH_SECONDS
        l, lc = lamp(flash)
        photo_status = "[FLASH]" if flash else "[    ]"
        draw_control_row(stdscr, y, l, lc, "📸", "2", "Take photo", photo_status, C_MENU,
                         C_WARN if flash else C_OFF)
        y += 1
        
        # [3] Motion detect - photos (5)
        l, lc = lamp(state["motion"])
        status = "[ON ]" if state["motion"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "👁", "3", "Motion detect - photos (5)",
                        status, C_MENU, lc)
        y += 1
        
        # [4] Recording (manual)
        l, lc = lamp(state["record_manual"])
        status = "[ON ]" if state["record_manual"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🎬", "4", "Recording (manual)",
                        status, C_MENU, lc)
        y += 1
        
        # [5] Motion detect - recording
        l, lc = lamp(state["record_on_motion"])
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
        
        # Pokaż status diagnostyki
        if state["diagnostics_requested"]:
            safe_addstr(stdscr, y, 0, "-- == WYSYŁANIE DIAGNOSTYKI... ===", C_WARN)
        else:
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
        
        if state["stream"] and state["stream_uptime"] > 0:
            uptime_str = time.strftime("%H:%M:%S", time.gmtime(state["stream_uptime"]))
            safe_addstr(stdscr, y, 15, f"UPTIME: {uptime_str}", C_INFO)
            safe_addstr(stdscr, y, 35, f"SEGMENTS: {state['segments_generated']}", C_INFO)
            y += 1
        
        # Statystyki na dole
        stats_line = f"Photos: {state['photos_taken']} | Recordings: {state['recordings_count']}"
        safe_addstr(stdscr, y, 0, stats_line, C_INFO)
        y += 1
        
        # Informacja o oczekującej komendzie
        if state["command_pending"]:
            safe_addstr(stdscr, y, 0, "⏳ Oczekiwanie na odpowiedź...", C_WARN)
            y += 1
    
    stdscr.refresh()

# ================= UI LOOP =================
def ui(stdscr):
    curses.curs_set(0)
    stdscr.timeout(100)  # 100ms timeout dla responsywności
    
    # Uruchom silnik jeśli nie działa
    if not is_engine_running():
        start_engine()
        time.sleep(1.0)
    
    # Uruchom MQTT
    mqtt_start()
    
    # Poczekaj na połączenie
    time.sleep(0.5)
    
    # Włącz streaming domyślnie
    ensure_streaming_on()
    
    # Diagnostyka startowa
    time.sleep(0.5)
    run_diagnostics()
    
    last_diag_poll = time.time()
    last_health_check = time.time()
    last_stream_check = time.time()
    
    while True:
        now = time.time()
        
        # Automatyczne odświeżanie diagnostyki co 5 sekund
        if now - last_diag_poll > 5.0 and not state["command_pending"]:
            run_diagnostics()
            last_diag_poll = now
        
        # Sprawdzanie zdrowia silnika co 3 sekundy
        if now - last_health_check > 3.0:
            check_engine_health()
            last_health_check = now
        
        # Sprawdzanie czy streaming jest włączony (co 2 sekundy jeśli wyłączony)
        if now - last_stream_check > 2.0 and not state["stream"] and not state["command_pending"]:
###            ensure_streaming_on()
            last_stream_check = now
        
        draw(stdscr)
        
        k = stdscr.getch()
        if k == -1:
            continue
        
        if k == ord('q'):
            # 1. Wyślij stream_off jeśli streaming działa
            if state["stream"]:
                _publish_cmd("stream_off")
                # Czekaj na wyłączenie (max 3 sekundy)
                wait_start = time.time()
                while time.time() - wait_start < 3.0:
                    with lock:
                        if not state["stream"]:
                            break
                    time.sleep(0.1)
                    draw(stdscr)
            
            # 2. Zatrzymaj MQTT
            mqtt_stop()
            
            # 3. Zatrzymaj silnik jeśli jeszcze działa
            if is_engine_running():
                subprocess.run(["pkill", "-f", ENGINE_PGREP],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            
            break
        
        elif k == ord('1'):
            with lock:
                want_off = state["stream"]
    
        if want_off:
            _publish_cmd("stream_off")
            else:
            _publish_cmd("stream_on")
            with lock:
                state["stream_requested"] = True

            run_diagnostics()

        elif k == ord('2'):
            _publish_cmd("photo")
            with lock:
                state["last_event"] = "📸 Wysyłam komendę photo..."
            run_diagnostics()
        
        elif k == ord('3'):
            with lock:
                want_off = state["motion"]
            
            if want_off:
                _publish_cmd("motion_off")
                with lock:
                    state["motion"] = False
            else:
                _publish_cmd("motion_on")
                with lock:
                    state["motion"] = True
            
            run_diagnostics()
        
        elif k == ord('4'):
            with lock:
                want_off = state["record_manual"]
            
            if want_off:
                _publish_cmd("rec_off")
                with lock:
                    state["record_manual"] = False
            else:
                _publish_cmd("rec_on")
                with lock:
                    state["record_manual"] = True
            
            run_diagnostics()
        
        elif k == ord('5'):
            with lock:
                want_off = state["record_on_motion"]
            
            if want_off:
                _publish_cmd("rec_motion_off")
                with lock:
                    state["record_on_motion"] = False
            else:
                _publish_cmd("rec_motion_on")
                with lock:
                    state["record_on_motion"] = True
            
            run_diagnostics()

# ================= MAIN ===================
def _sig_handler(*_):
    # Próba poprawnego wyjścia
    global client
    try:
        if client:
            client.publish(T_CMD, "stream_off", retain=False)
            time.sleep(0.5)
    except:
        pass
    raise SystemExit(0)

def main():
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
    curses.wrapper(ui)

if __name__ == "__main__":
    main()
