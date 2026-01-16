#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
hal_stream_ui_v4.py

UI = pilot. Silnik = mózg.
Ten plik:
- NIE uruchamia kamery/ffmpeg/ssh/http.
- Tylko wysyła komendy do silnika po MQTT i wyświetla status/logi/ack.

Wymaga:
  pip install paho-mqtt
Uruchom:
  python3 ~/HALbridge/hal_stream_ui_v4.py
"""

import curses
import json
import time
import threading
from collections import deque
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
T_DIAG = f"{BASE}/diag"       # jeśli silnik publikuje diag
T_HEALTH = f"{BASE}/health"   # jeśli silnik publikuje health
T_EVENT = f"{BASE}/event"     # jeśli silnik publikuje event


# ===================== UI CONFIG =====================
STATUS_POLL_SEC = 1.5
LOG_MAX = 300
ACK_MAX = 80
EVENT_MAX = 80
HEALTH_MAX = 80

KEY_HELP = [
    ("s", "start/stop stream"),
    ("1", "profile low"),
    ("2", "profile med"),
    ("3", "profile high"),
    ("p", "photo"),
    ("r", "rec_on/rec_off"),
    ("m", "motion_on/off"),
    ("f", "mphoto_on/off"),
    ("g", "mrec_on/off"),
    ("t", "tailscale on/off"),
    ("u", "status (poll now)"),
    ("q", "quit"),
]


def now_str():
    return datetime.now().strftime("%H:%M:%S")


class UIState:
    def __init__(self):
        self.lock = threading.RLock()

        self.connected = False
        self.last_mqtt_err = ""

        self.status = {}          # dict from T_STATUS
        self.health = {}          # dict from T_HEALTH (optional)
        self.last_status_ts = 0.0

        self.logs = deque(maxlen=LOG_MAX)
        self.acks = deque(maxlen=ACK_MAX)
        self.events = deque(maxlen=EVENT_MAX)
        self.health_msgs = deque(maxlen=HEALTH_MAX)

        self.want_recording = False
        self.want_motion = None
        self.want_mphoto = None
        self.want_mrec = None

    def push_log(self, line: str):
        with self.lock:
            self.logs.appendleft(line)

    def push_ack(self, line: str):
        with self.lock:
            self.acks.appendleft(line)

    def push_event(self, line: str):
        with self.lock:
            self.events.appendleft(line)

    def push_health_msg(self, line: str):
        with self.lock:
            self.health_msgs.appendleft(line)


STATE = UIState()


def safe_json_loads(payload: str):
    try:
        return json.loads(payload)
    except Exception:
        return None


def mqtt_send(client: mqtt.Client, cmd: str):
    cmd = (cmd or "").strip()
    if not cmd:
        return
    client.publish(T_CMD, cmd, retain=False)
    STATE.push_log(f"[{now_str()}] -> CMD: {cmd}")


def request_status(client: mqtt.Client):
    # Silnik ma komendę "status" (CLI); wysyłamy ją po MQTT
    mqtt_send(client, "status")


def fmt_bool(v):
    return "YES" if v else "no"


def draw_box(win, y, x, h, w, title=""):
    win.attron(curses.A_DIM)
    for i in range(w):
        try:
            win.addch(y, x + i, "-")
            win.addch(y + h - 1, x + i, "-")
        except curses.error:
            pass
    for i in range(h):
        try:
            win.addch(y + i, x, "|")
            win.addch(y + i, x + w - 1, "|")
        except curses.error:
            pass
    try:
        win.addch(y, x, "+")
        win.addch(y, x + w - 1, "+")
        win.addch(y + h - 1, x, "+")
        win.addch(y + h - 1, x + w - 1, "+")
    except curses.error:
        pass
    win.attroff(curses.A_DIM)
    if title:
        try:
            win.addstr(y, x + 2, f"[ {title} ]", curses.A_BOLD)
        except curses.error:
            pass


def draw_kv(win, y, x, k, v, k_attr=curses.A_BOLD, v_attr=0):
    try:
        win.addstr(y, x, f"{k}: ", k_attr)
        win.addstr(y, x + len(k) + 2, str(v), v_attr)
    except curses.error:
        pass


def short(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: max(0, n - 1)] + "…"


def status_get(d, path, default=None):
    cur = d
    for p in path:
        if not isinstance(cur, dict) or p not in cur:
            return default
        cur = cur[p]
    return cur


def render(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(150)

    while True:
        stdscr.erase()
        h, w = stdscr.getmaxyx()

        # Header
        title = "HAL STREAM UI v4 (pilot)  |  q quit"
        try:
            stdscr.addstr(0, 2, short(title, w - 4), curses.A_BOLD)
        except curses.error:
            pass

        # Layout regions
        top_h = 9
        mid_h = max(10, h - top_h - 9)
        bot_h = h - top_h - mid_h - 2

        # Boxes
        draw_box(stdscr, 1, 1, top_h, w - 2, "STATUS")
        draw_box(stdscr, 1 + top_h, 1, mid_h, w - 2, "LOGS / ACK / EVENTS")
        draw_box(stdscr, 1 + top_h + mid_h, 1, bot_h, w - 2, "KEYS")

        with STATE.lock:
            st = dict(STATE.status) if isinstance(STATE.status, dict) else {}
            connected = STATE.connected
            last_err = STATE.last_mqtt_err
            logs = list(STATE.logs)
            acks = list(STATE.acks)
            events = list(STATE.events)

        # STATUS content
        y0 = 2
        x0 = 3

        mqtt_stat = "connected" if connected else "DISCONNECTED"
        draw_kv(stdscr, y0, x0, "MQTT", mqtt_stat, v_attr=(curses.A_BOLD if connected else curses.A_BOLD | curses.A_REVERSE))
        if last_err and not connected:
            draw_kv(stdscr, y0 + 1, x0, "MQTT_ERR", short(last_err, w - x0 - 12), v_attr=curses.A_DIM)

        stream = bool(st.get("stream", False))
        http_ok = bool(st.get("http_ok", False))
        last_event = st.get("last_event", "")
        last_error = st.get("last_error", "")

        profile = st.get("profile", "")
        resolution = st.get("resolution", "")
        fps = st.get("fps", "")

        net_mode = status_get(st, ["network", "mode"], "")
        net_url = status_get(st, ["network", "public_stream_url"], "")
        tailscale_ip = status_get(st, ["network", "tailscale_ip"], None)

        stream_url_local = st.get("local_stream_url", "")
        hls_playlist = st.get("hls_playlist", "")

        # right column start
        xr = w // 2
        if xr < 40:
            xr = 3

        draw_kv(stdscr, y0, xr, "STREAM", fmt_bool(stream), v_attr=(curses.A_BOLD if stream else curses.A_DIM))
        draw_kv(stdscr, y0 + 1, xr, "HTTP_OK", fmt_bool(http_ok), v_attr=(curses.A_BOLD if http_ok else curses.A_DIM))

        draw_kv(stdscr, y0 + 2, xr, "PROFILE", profile)
        draw_kv(stdscr, y0 + 3, xr, "RES", resolution)
        draw_kv(stdscr, y0 + 4, xr, "FPS", fps)

        draw_kv(stdscr, y0 + 5, xr, "NET", net_mode)
        if tailscale_ip:
            draw_kv(stdscr, y0 + 6, xr, "TS_IP", tailscale_ip, v_attr=curses.A_DIM)

        # Left column
        draw_kv(stdscr, y0 + 2, x0, "LAST", short(last_event, 40))
        if last_error:
            draw_kv(stdscr, y0 + 3, x0, "ERR", short(last_error, 40), v_attr=curses.A_BOLD | curses.A_REVERSE)
        else:
            draw_kv(stdscr, y0 + 3, x0, "ERR", "none", v_attr=curses.A_DIM)

        if net_url:
            draw_kv(stdscr, y0 + 4, x0, "PUBLIC_URL", short(net_url, w - x0 - 15), v_attr=curses.A_DIM)
        elif stream_url_local:
            draw_kv(stdscr, y0 + 4, x0, "LOCAL_URL", short(stream_url_local, w - x0 - 14), v_attr=curses.A_DIM)

        if hls_playlist:
            draw_kv(stdscr, y0 + 5, x0, "PLAYLIST", short(hls_playlist, w - x0 - 14), v_attr=curses.A_DIM)

        # MID: split into 3 columns: logs / ack / events
        mid_y = 1 + top_h + 1
        mid_x = 3
        mid_w = w - 6
        col_w = max(20, mid_w // 3)

        logs_x = mid_x
        acks_x = mid_x + col_w
        events_x = mid_x + 2 * col_w

        # Titles
        try:
            stdscr.addstr(mid_y, logs_x, "LOG", curses.A_BOLD)
            stdscr.addstr(mid_y, acks_x, "ACK", curses.A_BOLD)
            stdscr.addstr(mid_y, events_x, "EVENT", curses.A_BOLD)
        except curses.error:
            pass

        # Content
        lines_avail = mid_h - 3
        for i in range(lines_avail):
            ly = mid_y + 1 + i
            if i < len(logs):
                try:
                    stdscr.addstr(ly, logs_x, short(logs[i], col_w - 1))
                except curses.error:
                    pass
            if i < len(acks):
                try:
                    stdscr.addstr(ly, acks_x, short(acks[i], col_w - 1), curses.A_DIM)
                except curses.error:
                    pass
            if i < len(events):
                try:
                    stdscr.addstr(ly, events_x, short(events[i], col_w - 1), curses.A_DIM)
                except curses.error:
                    pass

        # Bottom keys
        ky = 1 + top_h + mid_h + 1
        kx = 3
        row = 0
        col = 0
        for key, desc in KEY_HELP:
            text = f"{key}={desc}"
            if kx + col * 28 + len(text) + 2 > w - 3:
                row += 1
                col = 0
            try:
                stdscr.addstr(ky + row, kx + col * 28, short(text, 27), curses.A_DIM)
            except curses.error:
                pass
            col += 1

        stdscr.refresh()

        # Key handling
        try:
            ch = stdscr.getch()
        except Exception:
            ch = -1

        if ch == -1:
            continue

        if ch in (ord("q"), ord("Q")):
            return "quit"

        # stash commands; actual send happens via callback from main thread with client
        with STATE.lock:
            STATE._last_key = ch  # type: ignore


def mqtt_thread(stop_ev: threading.Event):
    def on_connect(c, *_):
        with STATE.lock:
            STATE.connected = True
            STATE.last_mqtt_err = ""
        c.subscribe(T_STATUS)
        c.subscribe(T_ACK)
        c.subscribe(T_LOG)
        c.subscribe(T_EVENT)
        c.subscribe(T_HEALTH)
        c.subscribe(T_DIAG)
        # poll immediately
        c.publish(T_CMD, "status", retain=False)

    def on_disconnect(c, *_):
        with STATE.lock:
            STATE.connected = False

    def on_message(c, _, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace").strip()

        if topic == T_LOG:
            STATE.push_log(f"[{now_str()}] {payload}")
            return

        if topic == T_ACK:
            j = safe_json_loads(payload)
            if isinstance(j, dict):
                cmd = j.get("cmd", "?")
                res = j.get("result", "?")
                m = j.get("msg", "")
                STATE.push_ack(f"[{now_str()}] {cmd} {res} {short(m, 120)}")
            else:
                STATE.push_ack(f"[{now_str()}] {short(payload, 160)}")
            return

        if topic == T_EVENT:
            j = safe_json_loads(payload)
            if isinstance(j, dict):
                t = j.get("type", "?")
                det = j.get("details", {})
                STATE.push_event(f"[{now_str()}] {t} {short(det, 120)}")
            else:
                STATE.push_event(f"[{now_str()}] {short(payload, 160)}")
            return

        if topic == T_HEALTH:
            STATE.push_health_msg(f"[{now_str()}] {short(payload, 160)}")
            return

        if topic == T_STATUS:
            j = safe_json_loads(payload)
            if isinstance(j, dict):
                with STATE.lock:
                    STATE.status = j
                    STATE.last_status_ts = time.time()
            else:
                STATE.push_log(f"[{now_str()}] STATUS decode failed: {short(payload, 160)}")
            return

        if topic == T_DIAG:
            STATE.push_log(f"[{now_str()}] DIAG: {short(payload, 200)}")
            return

    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=30)
    except Exception as e:
        with STATE.lock:
            STATE.connected = False
            STATE.last_mqtt_err = str(e)
        return

    # loop in background and also handle key->command mapping
    client.loop_start()

    last_poll = 0.0
    while not stop_ev.is_set():
        time.sleep(0.05)

        # periodic status poll
        now = time.time()
        if now - last_poll >= STATUS_POLL_SEC:
            last_poll = now
            try:
                client.publish(T_CMD, "status", retain=False)
            except Exception:
                pass

        # key commands
        ch = None
        with STATE.lock:
            if hasattr(STATE, "_last_key"):
                ch = getattr(STATE, "_last_key")
                delattr(STATE, "_last_key")

        if ch is None:
            continue

        # map keys to engine commands (sent to T_CMD)
        try:
            with STATE.lock:
                st = dict(STATE.status) if isinstance(STATE.status, dict) else {}
            stream = bool(st.get("stream", False))
            rec_active = bool(st.get("recording_active", False))
            motion_enabled = bool(st.get("motion_enabled", st.get("motion_detection", False)))
            mphoto_enabled = bool(st.get("motion_photo_enabled", False))
            mrec_enabled = bool(st.get("motion_record_enabled", False))
            net_mode = status_get(st, ["network", "mode"], "local")
        except Exception:
            stream = False
            rec_active = False
            motion_enabled = False
            mphoto_enabled = False
            mrec_enabled = False
            net_mode = "local"

        if ch in (ord("u"), ord("U")):
            request_status(client)

        elif ch in (ord("s"), ord("S")):
            mqtt_send(client, "stop" if stream else "start")

        elif ch == ord("1"):
            mqtt_send(client, "profile low")

        elif ch == ord("2"):
            mqtt_send(client, "profile med")

        elif ch == ord("3"):
            mqtt_send(client, "profile high")

        elif ch in (ord("p"), ord("P")):
            mqtt_send(client, "photo")

        elif ch in (ord("r"), ord("R")):
            mqtt_send(client, "rec_off" if rec_active else "rec_on")

        elif ch in (ord("m"), ord("M")):
            mqtt_send(client, "motion_off" if motion_enabled else "motion_on")

        elif ch in (ord("f"), ord("F")):
            mqtt_send(client, "mphoto_off" if mphoto_enabled else "mphoto_on")

        elif ch in (ord("g"), ord("G")):
            mqtt_send(client, "mrec_off" if mrec_enabled else "mrec_on")

        elif ch in (ord("t"), ord("T")):
            # Toggle tailscale based on status network.mode
            mqtt_send(client, "tailscale_off" if net_mode == "tailscale" else "tailscale_on")
            # ask status right after
            request_status(client)

    try:
        client.loop_stop()
    except Exception:
        pass
    try:
        client.disconnect()
    except Exception:
        pass


def main():
    stop_ev = threading.Event()
    th = threading.Thread(target=mqtt_thread, args=(stop_ev,), daemon=True)
    th.start()

    try:
        result = curses.wrapper(render)
        if result == "quit":
            stop_ev.set()
    except KeyboardInterrupt:
        stop_ev.set()
    finally:
        stop_ev.set()
        time.sleep(0.2)


if __name__ == "__main__":
    main()
