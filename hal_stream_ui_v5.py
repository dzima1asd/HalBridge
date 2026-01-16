#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses
import time
import json
import signal
import threading
from collections import deque
import traceback

import paho.mqtt.client as mqtt

# ================= MQTT =================
MQTT_BROKER = "127.0.0.1"
MQTT_PORT = 1883

BASE = "hal/stream"
T_CMD    = f"{BASE}/cmd"
T_STATUS = f"{BASE}/status"
T_ACK    = f"{BASE}/ack"
T_LOG    = f"{BASE}/log"
T_DIAG   = f"{BASE}/diag"
T_HEALTH = f"{BASE}/health"
T_EVENT  = f"{BASE}/event"

# ================= UI CONFIG =================
PHOTO_FLASH_SECONDS = 1.0
POLL_SECONDS = 2.0
DIAG_SECONDS = 20.0

# ================= STATE =================
lock = threading.RLock()
client = None

log_ring = deque(maxlen=200)

state = {
    "mqtt_ok": False,
    "last_event": "boot",
    "last_ack": "",
    "last_diag": [],
    "last_diag_text": "",
    "last_photo_ts": 0.0,

    "stream": False,
    "engine_running": False,  # ustawiane na True dopiero gdy dostaniemy status/ack

    # Features (stary styl nazw)
    "motion": False,
    "record_manual": False,
    "record_on_motion": False,
    "recording_active": False,

    # Stats
    "photos_taken": 0,
    "recordings_count": 0,
    "segments_generated": 0,
    "stream_uptime": 0,

    # Nowe rzeczy z silnika v4
    "profile": "high",
    "resolution": "",
    "fps": 0,

    "network_mode": "local",     # local / tailscale
    "stream_url": "",            # public_stream_url albo local url z silnika

    # Komponenty health (mapowane ze status/health)
    "components": {
        "mqtt": "failed",
        "ssh": "unknown",
        "camera": "unknown",
        "ffmpeg": "unknown",
        "http": "unknown",
        "hls": "unknown",
    },

    # Flagi pomocnicze (pod UI)
    "pi_ok": False,
    "http_ok": False,
}

def _log(msg: str):
    try:
        ts = time.strftime("%H:%M:%S")
        log_ring.append(f"[{ts}] {msg}")
    except Exception:
        pass

# ================= MQTT HELPERS =================
def _publish_cmd(cmd: str):
    global client
    if not client:
        return
    try:
        client.publish(T_CMD, cmd, retain=False)
    except Exception as e:
        _log(f"publish_cmd error: {e}")

def run_diagnostics():
    _publish_cmd("status")
    # _publish_cmd("diag")

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
    c.subscribe(T_HEALTH)
    c.subscribe(T_EVENT)

    _publish_cmd("status")
    _publish_cmd("diag")

def on_disconnect(c, userdata, rc, properties=None):
    with lock:
        state["mqtt_ok"] = False
        state["components"]["mqtt"] = "failed"
        state["engine_running"] = False
        state["last_event"] = "⚠ MQTT disconnected"

def _map_health_block_to_components(health: dict):
    # health w nowym silniku może mieć różne klucze - mapujemy łagodnie
    # preferowane UI keys: ssh, camera, ffmpeg, http, hls
    for k, v in health.items():
        kk = str(k)
        vv = str(v)
        if kk in ("ssh", "ssh_connection"):
            state["components"]["ssh"] = vv
        elif kk in ("camera", "pi_camera", "pi_camera_health"):
            state["components"]["camera"] = vv
        elif kk in ("ffmpeg",):
            state["components"]["ffmpeg"] = vv
        elif kk in ("http", "http_server"):
            state["components"]["http"] = vv
        elif kk in ("hls", "hls_output"):
            state["components"]["hls"] = vv
        elif kk == "mqtt":
            state["components"]["mqtt"] = vv

    # update flags
    state["pi_ok"] = (state["components"].get("camera") == "healthy")
    state["http_ok"] = (state["components"].get("http") == "healthy")

def _parse_json(payload: str):
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except Exception:
        return {}

def on_message(c, userdata, msg):
    topic = msg.topic
    payload = msg.payload.decode(errors="ignore")

    with lock:
        # Silnik "żyje", jeśli cokolwiek do nas gada na kontrolowanych topicach
        if topic in (T_STATUS, T_ACK, T_HEALTH, T_EVENT, T_DIAG, T_LOG):
            state["engine_running"] = True

        if topic == T_STATUS:
            try:
                s = _parse_json(payload)

                # stream booleans
                engine_state = s.get("state", "")
                state["stream"] = (engine_state == "active")

                # features mapping (nowy status->old UI flags)
                features = s.get("features", {})
                if isinstance(features, dict):
                    state["record_manual"] = bool(features.get("manual_record", state["record_manual"]))
                    state["motion"] = bool(features.get("motion_detection", state["motion"]))
                    state["record_on_motion"] = bool(features.get("auto_record", state["record_on_motion"]))
                    state["recording_active"] = bool(s.get("recording_active", state["recording_active"]))

                # stats (źródłem prawdy jest T_STATUS z silnika)
                stats = s.get("stats", {})
                if isinstance(stats, dict):
                    # HLS / segmenty
                    if "segments_total" in stats:
                        state["segments_generated"] = int(stats.get("segments_total") or 0)
                    elif "segments_session" in stats:
                        state["segments_generated"] = int(stats.get("segments_session") or 0)

                    # uptime streamu
                    if "duration" in stats:
                        state["stream_uptime"] = int(stats.get("duration") or 0)

                    # liczniki
                    if "photos_taken" in stats:
                        state["photos_taken"] = int(stats.get("photos_taken") or 0)

                    if "recordings_count" in stats:
                        state["recordings_count"] = int(stats.get("recordings_count") or 0)

                # profile / res / fps (jeśli silnik podaje)
                state["profile"] = s.get("profile", state["profile"]) or state["profile"]
                state["resolution"] = s.get("resolution", state["resolution"]) or state["resolution"]
                try:
                    state["fps"] = int(s.get("fps", state["fps"]) or state["fps"])
                except Exception:
                    pass

                # network
                net = s.get("network", {})
                if isinstance(net, dict):
                    state["network_mode"] = net.get("mode", state["network_mode"]) or state["network_mode"]
                    state["stream_url"] = net.get("public_stream_url", state["stream_url"]) or state["stream_url"]

                # last event
                le = s.get("last_event")
                if le:
                    state["last_event"] = str(le)

                # health block
                health = s.get("health", {})
                if isinstance(health, dict):
                    _map_health_block_to_components(health)

            except Exception as e:
                _log(f"UI error: status parse: {e}")

        elif topic == T_HEALTH:
            try:
                data = _parse_json(payload)
                health = data.get("health", {})
                if isinstance(health, dict):
                    _map_health_block_to_components(health)
            except Exception as e:
                _log(f"UI error: health parse: {e}")

        elif topic == T_EVENT:
            try:
                data = _parse_json(payload)
                event_type = data.get("type", "")
                details = data.get("details", {}) if isinstance(data.get("details", {}), dict) else {}

                # Eventy NIE zmieniają stanu logicznego.
                # Służą wyłącznie do komunikatów UI.
                if event_type == "photo_captured":
                    state["last_event"] = "📸 Photo saved"
                    state["last_photo_ts"] = time.time()

                elif event_type == "recording_started":
                    state["last_event"] = "🎬 Recording started"

                elif event_type == "recording_stopped":
                    state["last_event"] = "🎬 Recording stopped"

                elif event_type == "stream_started":
                    state["last_event"] = "📡 Stream started"

                elif event_type == "stream_stopped":
                    state["last_event"] = "📡 Stream stopped"

                elif event_type == "error":
                    msg_txt = str(details.get("message", "Unknown"))[:120]
                    state["last_event"] = f"❌ Error: {msg_txt}"

                elif event_type == "warning":
                    msg_txt = str(details.get("message", "Unknown"))[:120]
                    state["last_event"] = f"⚠ Warning: {msg_txt}"

            except Exception as e:
                _log(f"UI error: event parse: {e}")

        elif topic == T_ACK:
            # ACK może być stringiem albo JSON-em
            try:
                data = _parse_json(payload)
                if isinstance(data, dict) and data:
                    # Spróbuj ująć "cmd"/"ok"/"msg", inaczej pokaż całość skrótowo
                    cmd = data.get("cmd") or data.get("command") or ""
                    ok = data.get("ok")
                    msg_txt = data.get("msg") or data.get("message") or ""
                    if cmd or msg_txt or ok is not None:
                        ok_txt = ""
                        if ok is True:
                            ok_txt = "✅"
                        elif ok is False:
                            ok_txt = "❌"
                        state["last_ack"] = f"{ok_txt} {cmd} {msg_txt}".strip()
                    else:
                        state["last_ack"] = json.dumps(data, ensure_ascii=False)[:240]
                else:
                    state["last_ack"] = (payload or "").strip()[:240]
            except Exception as e:
                state["last_ack"] = (payload or "").strip()[:240]
                _log(f"UI error: ack parse: {e}")

        elif topic == T_LOG:
            try:
                txt = (payload or "").rstrip()
                if txt:
                    _log(f"ENGINE: {txt[:300]}")
            except Exception as e:
                _log(f"UI error: log parse: {e}")

        elif topic == T_DIAG:
            try:
                data = _parse_json(payload)
                # diag może być listą/str/dict zależnie od silnika
                if isinstance(data, dict):
                    # preferuj "lines" albo "text"
                    lines = data.get("lines")
                    text = data.get("text")
                    if isinstance(lines, list):
                        state["last_diag"] = [str(x) for x in lines][:50]
                    elif isinstance(text, str):
                        state["last_diag_text"] = text[:2000]
                    else:
                        state["last_diag_text"] = json.dumps(data, ensure_ascii=False)[:2000]
                elif isinstance(data, list):
                    state["last_diag"] = [str(x) for x in data][:50]
                else:
                    if payload:
                        state["last_diag_text"] = payload[:2000]
            except Exception as e:
                _log(f"UI error: diag parse: {e}")

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
    except Exception as e:
        _log(f"mqtt_stop error: {e}")
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
        stdscr.addstr(y, x, str(text)[: max(0, w - x - 1)], color)
    except Exception:
        pass

def lamp(v, c_on, c_off):
    # zachowujemy styl: 🔴 aktywny, ⚪ nieaktywny
    if v:
        return ("🔴", c_on)
    return ("⚪", c_off)

def draw_control_row(stdscr, y, lamp_char, lamp_color, icon, key, name, value, c_info, c_val):
    safe_addstr(stdscr, y, 2, lamp_char, lamp_color)
    safe_addstr(stdscr, y, 6, icon, c_info)
    safe_addstr(stdscr, y, 10, f"[{key}]", c_info)
    safe_addstr(stdscr, y, 15, f"{name:<20}", c_info)
    safe_addstr(stdscr, y, 37, ":", c_info)
    safe_addstr(stdscr, y, 40, value, c_val)

def build_diagnostics_text():
    diag_lines = []

    url = state["stream_url"] or "(brak url)"
    diag_lines.append(f"- URL: {url}")

    diag_lines.append("- [0] Procesy")
    diag_lines.append("- SILNIK: DZIAŁA" if state["engine_running"] else "- (brak)")

    diag_lines.append("- [1] Parametry")
    prof = state.get("profile", "")
    res = state.get("resolution", "")
    fps = state.get("fps", 0)
    diag_lines.append(f"- profile={prof}")
    if res:
        diag_lines.append(f"- res={res} fps={fps}")
    else:
        diag_lines.append(f"- fps={fps}")

    diag_lines.append("- [2] Pi camera")
    diag_lines.append(f"- {'OK' if state['pi_ok'] else 'BRAK'}")

    diag_lines.append("- [3] HTTP HLS")
    diag_lines.append("- OK" if state["http_ok"] else "- (brak)")

    diag_lines.append("- [4] Network")
    diag_lines.append(f"- mode={state.get('network_mode','local')}")

    return diag_lines

# ================= DRAW =================
def draw(stdscr):
    stdscr.clear()
    curses.start_color()

    curses.init_pair(1, curses.COLOR_GREEN, curses.COLOR_BLACK)
    curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_CYAN, curses.COLOR_BLACK)
    curses.init_pair(4, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(5, curses.COLOR_GREEN, curses.COLOR_BLACK)

    C_OK   = curses.color_pair(1)
    C_OFF  = curses.color_pair(2)
    C_INFO = curses.color_pair(3)
    C_MENU = curses.color_pair(4)
    C_WARN = curses.color_pair(5)

    with lock:
        y = 1

        safe_addstr(stdscr, y, 0, "STREAM URL", C_INFO)
        y += 1
        safe_addstr(stdscr, y, 0, state["stream_url"] or "", C_OK)
        y += 2

        safe_addstr(stdscr, y, 0, "STEROWANIE - TRYB PRACY", C_MENU)
        y += 1

        l, lc = lamp(state["stream"], C_WARN, C_OFF)
        status = "[ON ]" if state["stream"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🎥", "1", "Stream", status, C_MENU, lc)
        y += 1

        flash = (time.time() - state["last_photo_ts"]) < PHOTO_FLASH_SECONDS
        l, lc = lamp(flash, C_WARN, C_OFF)
        photo_status = "[FLASH]" if flash else "[    ]"
        draw_control_row(
            stdscr, y, l, lc, "📸", "2", "Take photo",
            photo_status, C_MENU, (C_WARN if flash else C_OFF)
        )
        y += 1

        l, lc = lamp(state["motion"], C_WARN, C_OFF)
        status = "[ON ]" if state["motion"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "👁", "3", "Motion detect - photos (5)", status, C_MENU, lc)
        y += 1

        l, lc = lamp(state["record_manual"], C_WARN, C_OFF)
        status = "[ON ]" if state["record_manual"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🎬", "4", "Recording (manual)", status, C_MENU, lc)
        y += 1

        l, lc = lamp(state["record_on_motion"], C_WARN, C_OFF)
        status = "[ON ]" if state["record_on_motion"] else "[OFF]"
        draw_control_row(stdscr, y, l, lc, "🧠", "5", "Motion detect - recording", status, C_MENU, lc)
        y += 1

        is_low = (state.get("profile") == "low")
        l, lc = lamp(is_low, C_WARN, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🎛", "6", "Profile low", "[SET]" if is_low else "[   ]", C_MENU, lc)
        y += 1

        is_med = (state.get("profile") == "med")
        l, lc = lamp(is_med, C_WARN, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🎛", "7", "Profile med", "[SET]" if is_med else "[   ]", C_MENU, lc)
        y += 1

        is_high = (state.get("profile") == "high")
        l, lc = lamp(is_high, C_WARN, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🎛", "8", "Profile high", "[SET]" if is_high else "[   ]", C_MENU, lc)
        y += 1

        ts_on = (state.get("network_mode") == "tailscale")
        l, lc = lamp(ts_on, C_WARN, C_OFF)
        draw_control_row(stdscr, y, l, lc, "🌐", "9", "Tailscale", "[ON ]" if ts_on else "[OFF]", C_MENU, lc)
        y += 2

        safe_addstr(stdscr, y, 0, "[q] Quit (graceful)", C_MENU)
        y += 2

        safe_addstr(stdscr, y, 0, "Ostatnie zdarzenie:", C_INFO)
        y += 1
        safe_addstr(stdscr, y, 0, state["last_event"], C_OFF)
        y += 1
        if state.get("last_ack"):
            safe_addstr(stdscr, y, 0, state["last_ack"][:200], C_OFF)
            y += 1

        # pokaż kilka ostatnich logów z silnika/UI
        if log_ring:
            safe_addstr(stdscr, y, 0, "Log (ostatnie):", C_INFO)
            y += 1
            for line in list(log_ring)[-5:]:
                safe_addstr(stdscr, y, 0, line, C_OFF)
                y += 1

        y += 1
        safe_addstr(stdscr, y, 0, "DIAGNOSTYKA (z silnika)", C_INFO)
        y += 1
        safe_addstr(stdscr, y, 0, "-- == STREAM DIAGNOSTYKA ===", C_INFO)
        y += 1

        diag_lines = build_diagnostics_text()
        for line in diag_lines[:12]:
            safe_addstr(stdscr, y, 0, line, C_INFO)
            y += 1

        # jeśli diag przyszedł jako lines/text, pokaż skrót
        if state.get("last_diag"):
            safe_addstr(stdscr, y, 0, "Diag:", C_INFO)
            y += 1
            for line in state["last_diag"][:6]:
                safe_addstr(stdscr, y, 0, f"- {line}"[:200], C_OFF)
                y += 1
        elif state.get("last_diag_text"):
            safe_addstr(stdscr, y, 0, "Diag:", C_INFO)
            y += 1
            txt = state["last_diag_text"].replace("\r", " ").replace("\n", " ")
            safe_addstr(stdscr, y, 0, txt[:200], C_OFF)
            y += 1

        y += 1
        mqtt_status = "OK" if state["mqtt_ok"] else "BRAK"
        mqtt_color = C_OK if state["mqtt_ok"] else C_WARN
        safe_addstr(stdscr, y, 0, f"MQTT: {mqtt_status}", mqtt_color)

        if state["stream"]:
            uptime_str = time.strftime("%H:%M:%S", time.gmtime(max(0, int(state["stream_uptime"]))))
            safe_addstr(stdscr, y, 15, f"UPTIME: {uptime_str}", C_INFO)
            safe_addstr(stdscr, y, 35, f"SEGMENTS: {state['segments_generated']}", C_INFO)
        y += 1

        prof = state.get("profile", "")
        res = state.get("resolution", "")
        fps = state.get("fps", 0)
        safe_addstr(stdscr, y, 0, f"PROFILE: {prof} | RES: {res} | FPS: {fps} | NET: {state.get('network_mode','')}", C_INFO)
        y += 1

        stats_line = f"Photos: {state['photos_taken']} | Recordings: {state['recordings_count']}"
        safe_addstr(stdscr, y, 0, stats_line, C_INFO)

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

    mqtt_start()
    time.sleep(0.2)
    run_diagnostics()

    with lock:
        state["last_event"] = "✅ UI uruchomione"

    last_poll = 0.0
    last_diag = 0.0

    while True:
        now = time.time()

        if now - last_poll > POLL_SECONDS:
            _publish_cmd("status")
            last_poll = now

        if now - last_diag > DIAG_SECONDS:
            _publish_cmd("diag")
            last_diag = now

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
                if state["stream"]:
                    _publish_cmd("stop")
                    state["last_event"] = "⏳ Stopping stream..."
                else:
                    _publish_cmd("start")
                    state["last_event"] = "⏳ Starting stream..."
            run_diagnostics()

        elif k == ord('2'):
            _publish_cmd("photo")
            run_diagnostics()

        elif k == ord('3'):
            if state["motion"]:
                _publish_cmd("motion_off")
                state["last_event"] = "⏳ Motion detect OFF..."
            else:
                _publish_cmd("motion_on")
                state["last_event"] = "⏳ Motion detect ON..."
            run_diagnostics()

        elif k == ord('4'):
            if state["record_manual"]:
                _publish_cmd("rec_off")
                state["last_event"] = "⏳ Stopping recording..."
            else:
                _publish_cmd("rec_on")
                state["last_event"] = "⏳ Starting recording..."
            run_diagnostics()

        elif k == ord('5'):
            if state["record_on_motion"]:
                _publish_cmd("mrec_off")
                state["last_event"] = "⏳ Motion→record OFF..."
            else:
                _publish_cmd("mrec_on")
                state["last_event"] = "⏳ Motion→record ON..."
            run_diagnostics()

        elif k == ord('6'):
            _publish_cmd("profile low")
            run_diagnostics()

        elif k == ord('7'):
            _publish_cmd("profile med")
            run_diagnostics()

        elif k == ord('8'):
            _publish_cmd("profile high")
            run_diagnostics()

        elif k == ord('9'):
            ts_on = (state.get("network_mode") == "tailscale")
            _publish_cmd("tailscale_off" if ts_on else "tailscale_on")
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
