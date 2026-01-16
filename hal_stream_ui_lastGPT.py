#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# hal_stream_ui.py
# UI + sterowanie po MQTT + prezentacja diagnostyki z mqtt_stream.py

import curses
import time
import signal
import json
import threading
import subprocess
from collections import deque

import paho.mqtt.client as mqtt

ENGINE_CMD = ["python3", "/home/hal/HALbridge/mqtt_stream.py"]
ENGINE_PGREP = "mqtt_stream.py"

# ================= KONFIG =================

TAILSCALE_IP = "100.80.82.126"
HTTP_PORT = 8081
STREAM_URL = f"http://{TAILSCALE_IP}:{HTTP_PORT}/stream.m3u8"

MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

BASE = "hal/stream"
T_CMD = f"{BASE}/cmd"
T_STATUS = f"{BASE}/status"
T_ACK = f"{BASE}/ack"
T_LOG = f"{BASE}/log"
T_DIAG = f"{BASE}/diag"

PHOTO_FLASH_SECONDS = 0.5

# ================= STAN ===================

state = {
    # tryby/akcje (z silnika)
    "stream": False,
    "motion": False,               # motion -> photos
    "record_manual": False,        # recording manual
    "record_on_motion": False,     # motion -> recording
    "recording_active": False,

    # diagnostyka / info (z silnika)
    "mqtt_ok": False,
    "pi_ok": False,
    "http_ok": False,

    "last_event": "init",
    "last_diag": [],
    "last_photo_ts": 0.0,
    "last_diag_text": "",
    "last_ack": "",
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

def _parse_diag_to_lamps(diag_text: str):
    # Lampki: ENGINE (mqtt_ok) i Pi camera
    pi_ok = False
    engine_ok = False

    # ENGINE = mamy MQTT i dostajemy jakiekolwiek DIAG
    if diag_text:
        engine_ok = True

    lines = diag_text.splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()

        # Kamera Pi: szukamy "OK" w sekcji [2]
        if s.startswith("[2]"):
            for j in range(i + 1, min(i + 6, len(lines))):
                t = lines[j].strip()
                if not t or t.startswith("["):
                    break
                if "OK" in t:
                    pi_ok = True
                    break

    return pi_ok, engine_ok

# ================= MQTT CALLBACKS =================

def on_connect(c, userdata, flags, rc, properties=None):
    with lock:
        state["mqtt_ok"] = True
        state["last_event"] = "✅ MQTT connected"

    c.subscribe(T_STATUS)
    c.subscribe(T_DIAG)
    c.subscribe(T_ACK)
    c.subscribe(T_LOG)

    # po połączeniu MQTT silnik JUŻ subskrybuje → można wysyłać komendy
    c.publish(T_CMD, "status", retain=False)
    c.publish(T_CMD, "diag", retain=False)
    c.publish(T_CMD, "stream_on", retain=False)

def on_disconnect(c, userdata, rc, properties=None):
    with lock:
        state["mqtt_ok"] = False
        state["last_event"] = "⚠ MQTT disconnected"


def on_message(c, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore")

    with lock:
        if topic == T_STATUS:
            try:
                s = json.loads(payload)

                state["stream"] = bool(s.get("stream", False))
                state["motion"] = bool(s.get("motion", False))
                state["http_ok"] = bool(s.get("http_ok", False))
                state["record_manual"] = bool(s.get("record_manual", False))
                state["record_on_motion"] = bool(s.get("record_on_motion", False))
                state["recording_active"] = bool(s.get("recording_active", False))

                le = s.get("last_event")
                if le:
                    state["last_event"] = le
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
            state["pi_ok"] = ("OK" in diag_text)
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
    return ("🟢", c_on) if v else ("⚪", c_off)


def draw_control_row(stdscr, y, lamp_char, lamp_color, icon, key, name, value, c_info, c_val):
    safe_addstr(stdscr, y, 2, lamp_char, lamp_color)
    safe_addstr(stdscr, y, 6, icon, c_info)
    safe_addstr(stdscr, y, 10, f"[{key}]", c_info)
    safe_addstr(stdscr, y, 15, f"{name:<26}", c_info)
    safe_addstr(stdscr, y, 42, ":", c_info)
    safe_addstr(stdscr, y, 46, value, c_val)


def draw(stdscr):
    stdscr.clear()
    curses.start_color()

    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)   # OK / ON
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)   # OFF
    curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)    # INFO
    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # MENU/AKCJE
    curses.init_pair(5, curses.COLOR_RED, curses.COLOR_BLACK)     # WARN

    C_OK = curses.color_pair(1)
    C_OFF = curses.color_pair(2)
    C_INFO = curses.color_pair(3)

    with lock:
        y = 1
        safe_addstr(stdscr, y, 2, "🧠 HAL STREAM ENGINE", C_INFO); y += 2

        safe_addstr(stdscr, y, 2, "📊 STATUS SYSTEMU", C_INFO); y += 1

        l, lc = lamp(state["mqtt_ok"], C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "📡", "-", "MQTT", "OK" if state["mqtt_ok"] else "BRAK", C_INFO, lc); y += 1

        l, lc = lamp(state["pi_ok"], C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "📷", "-", "Kamera Pi", "POŁĄCZONA" if state["pi_ok"] else "BRAK", C_INFO, lc); y += 1

        http_visible = state["stream"] and state["http_ok"]
        l, lc = lamp(http_visible, C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🌐", "-", "ENGINE", "NASŁUCH" if state["http_ok"] else "BRAK", C_INFO, lc); y += 2

        safe_addstr(stdscr, y, 2, "🔗 STREAM URL", C_INFO); y += 1
        safe_addstr(stdscr, y, 4, STREAM_URL, C_OK); y += 2

        safe_addstr(stdscr, y, 2, "⚙ STEROWANIE - TRYB PRACY", C_INFO); y += 1

        l, lc = lamp(state["stream"], C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🎥", "1", "Stream", f"[{'ON ' if state['stream'] else 'OFF'}]", C_INFO, lc); y += 1

        flash = (time.time() - state["last_photo_ts"]) < PHOTO_FLASH_SECONDS
        l, lc = lamp(flash, C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "📸", "2", "Take photo", "[   ]", C_INFO, (C_OK if flash else C_OFF)); y += 1

        l, lc = lamp(state["motion"], C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "👁", "3", "Motion detect → photos (5)", f"[{'ON ' if state['motion'] else 'OFF'}]", C_INFO, lc); y += 1

        l, lc = lamp(state["record_manual"], C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🎬", "4", "Recording (manual)", f"[{'ON ' if state['record_manual'] else 'OFF'}]", C_INFO, lc); y += 1

        l, lc = lamp(state["record_on_motion"], C_OK, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🧠", "5", "Motion detect → recording", f"[{'ON ' if state['record_on_motion'] else 'OFF'}]", C_INFO, lc); y += 2

        safe_addstr(stdscr, y, 10, "[q] Quit (graceful)", C_INFO); y += 2

        safe_addstr(stdscr, y, 2, "📝 Ostatnie zdarzenie:", C_INFO); y += 1
        safe_addstr(stdscr, y, 4, state["last_event"], C_INFO); y += 1
        if state.get("last_ack"):
            safe_addstr(stdscr, y, 4, state["last_ack"][:200], C_OFF); y += 1
        y += 1

        if state["last_diag"]:
            safe_addstr(stdscr, y, 2, "🧪 DIAGNOSTYKA (z silnika mqtt_stream.py):", C_INFO); y += 1
            for line in state["last_diag"][:12]:
                safe_addstr(stdscr, y, 4, f"- {line}"[:200], C_INFO); y += 1

    stdscr.refresh()


# ================= UI LOOP =================

def ui(stdscr):
    curses.curs_set(0)
    stdscr.timeout(100)

    start_engine()
    mqtt_start()

    time.sleep(0.2)
    run_diagnostics()
###    _publish_cmd("stream_on")

    with lock:
        state["last_event"] = "✅ UI uruchomione, wysyłam stream_on"

    last_poll = 0.0

    while True:
        now = time.time()
###        if now - last_poll > 2.0:
###            run_diagnostics()
###            last_poll = now

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
