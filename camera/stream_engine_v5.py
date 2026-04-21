#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import signal
import threading
import subprocess
import logging
from logging.handlers import RotatingFileHandler
import queue
from datetime import datetime
from typing import Optional
from camera.engine_state import EngineState, EngineMode
import paho.mqtt.client as mqtt
from camera.config import *
from camera.pipeline.stream_pipeline import StreamPipeline
from camera.engine_state import EngineState, EngineMode
from camera.http_server import HLSHttpServer
from camera.services.motion_service import MotionService
from camera.services.snapshot_service import SnapshotService
from camera.services.recorder_service import RecorderService

# ========================= HELPERY =========================

def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def ensure_dirs():
    os.makedirs(STREAM_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    os.makedirs(PHOTO_DIR, exist_ok=True)
    os.makedirs(REC_DIR, exist_ok=True)


def clear_hls():
    try:
        for fn in os.listdir(STREAM_DIR):
            if fn.endswith(".ts") or fn == "stream.m3u8":
                try:
                    os.remove(os.path.join(STREAM_DIR, fn))
                except Exception:
                    pass
    except FileNotFoundError:
        pass


def hls_ready() -> bool:
    return os.path.isfile(HLS_PLAYLIST) and os.path.getsize(HLS_PLAYLIST) > 0


def count_segments() -> int:
    try:
        return len([x for x in os.listdir(STREAM_DIR) if x.endswith(".ts")])
    except Exception:
        return 0


def _run(cmd: list, timeout=7):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def tailscale_is_running() -> bool:
    try:
        r = _run([TAILSCALE_BIN, "status"], timeout=5)
        return r.returncode == 0 and "Logged out." not in r.stdout
    except Exception:
        return False


def tailscale_ip_v4() -> Optional[str]:
    try:
        r = _run([TAILSCALE_BIN, "ip", "-4"], timeout=5)
        if r.returncode == 0:
            line = r.stdout.strip().splitlines()
            return line[0].strip() if line else None
    except Exception:
        pass
    return None


def kill_remote_rpicam():
    cmd = (
        "pkill -TERM -f rpicam-vid 2>/dev/null || true; "
        "sleep 0.3; "
        "pkill -KILL -f rpicam-vid 2>/dev/null || true"
    )
    subprocess.run(["ssh","-o","BatchMode=yes","-o","ConnectTimeout=3","-o","ServerAliveInterval=2","-o","ServerAliveCountMax=1",*SSH_OPTS,PI_HOST,cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)

class StreamEngine:
    def __init__(self):
        self.state = EngineState()

        # ===== motion rotating file logger =====
        log_dir = LOG_DIR
        os.makedirs(log_dir, exist_ok=True)

        self.motion_logger = logging.getLogger("motion_logger")
        self.motion_logger.setLevel(logging.INFO)

        if not self.motion_logger.handlers:
            handler = RotatingFileHandler(
                os.path.join(log_dir, "motion.log"),
                maxBytes=5 * 1024 * 1024,
                backupCount=5
            )
            formatter = logging.Formatter("%(asctime)s %(message)s")
            handler.setFormatter(formatter)
            self.motion_logger.addHandler(handler)


        # defaults (can be overridden by persisted state)
        self.profile = ""
        self.resolution = "1280x720"
        self.fps = 30

        self._load_state()

        self.lock = threading.RLock()

        self.proc_pi: Optional[subprocess.Popen] = None
        self.proc_hls: Optional[subprocess.Popen] = None
        self.stop_event = threading.Event()
        self.watchdog_thread: Optional[threading.Thread] = None
        self.mqtt_client: Optional[mqtt.Client] = None
        self.mqtt_thread: Optional[threading.Thread] = None

        self.cli_queue = queue.Queue()
        self.cli_stop = threading.Event()
        self.restart_in_progress = threading.Event()
        self.mqtt_queue = queue.Queue()
        self.cmd_queue = queue.Queue()
        self.cmd_worker_thread = None
        self.mqtt_stop_event = threading.Event()
        self.pipeline = StreamPipeline()
        self.http = HLSHttpServer(HTTP_BIND, HTTP_PORT, STREAM_DIR)

        self.motion = MotionService(
            stop_event=self.stop_event,
            is_stream_running=lambda: self.state.is_running(),
            is_http_running=lambda: self.http.is_running(),
            hls_ready=hls_ready,
            count_segments=count_segments,
            on_motion_cb=self._on_motion_event,
            log=self.log,
        )

        self.snapshot = SnapshotService(
            is_stream_running=lambda: self.state.is_running(),
            is_http_running=lambda: self.http.is_running(),
            hls_ready=hls_ready,
            log=self.log,
        )

        self.recorder = RecorderService(
            is_stream_running=lambda: self.state.is_running(),
            is_http_running=lambda: self.http.is_running(),
            hls_ready=hls_ready,
            log=self.log,
            rec_dir=REC_DIR,
            local_stream_url=LOCAL_STREAM_URL,
        )
    # ------------------- LOG -------------------


    # ====== STATE PERSISTENCE (class methods) ======

    def _load_state(self):
        try:
            from pathlib import Path
            import json
            from camera.config import STATE_FILE

            path = Path(STATE_FILE)
            if not path.exists():
                return

            data = json.loads(path.read_text(errors="ignore") or "{}")

            self.profile = data.get("profile", getattr(self, "profile", ""))
            self.resolution = data.get("resolution", getattr(self, "resolution", "1280x720"))
            self.fps = int(data.get("fps", getattr(self, "fps", 30)))

            feats = (data.get("features", {}) or {})

            # ONE SOURCE OF TRUTH: engine flags
            self.state.motion_enabled = bool(feats.get("motion_detection", getattr(self.state, "motion_enabled", True)))
            self.state.motion_record_enabled = bool(feats.get("auto_record", getattr(self.state, "motion_record_enabled", True)))
            self.state.motion_photo_enabled = bool(feats.get("motion_photo", getattr(self.state, "motion_photo_enabled", False)))

            # zsynchronizuj motion worker
            try:
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass

            self.log("state: loaded")
        except Exception as e:
            try:
                self.log(f"state: load error {e}")
            except Exception:
                pass

    def _save_state(self):
        try:
            from pathlib import Path
            import json
            from camera.config import STATE_FILE

            path = Path(STATE_FILE)
            path.parent.mkdir(parents=True, exist_ok=True)

            data = {
                "profile": getattr(self, "profile", ""),
                "resolution": getattr(self, "resolution", "1280x720"),
                "fps": int(getattr(self, "fps", 30)),
                "features": {
                    "motion_detection": bool(getattr(self.state, "motion_enabled", True)),
                    "auto_record": bool(getattr(self.state, "motion_record_enabled", True)),
                    "motion_photo": bool(getattr(self.state, "motion_photo_enabled", False)),
                },
            }

            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        except Exception as e:
            try:
                self.log(f"state: save error {e}")
            except Exception:
                pass



    
    def log(self, msg: str):
        # zawsze zdefiniuj line, bo Python nie lubi telepatii
        try:
            line = f"[{ts()}] {msg}"
        except Exception:
            line = str(msg)

        # do terminala
        try:
            print(line, flush=True)
        except Exception:
            pass

        # do logu ogólnego
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(os.path.join(LOG_DIR, "engine.log"), "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def set_event(self, ev: str, err: str = ""):
        with self.lock:
            self.state.last_event = ev
            self.state.last_error = err

    # ------------------- MQTT PUBLISH -------------------

    def mqtt_publish(self, topic: str, payload: str, retain: bool = False):
        c = self.mqtt_client
        if not c:
            return
        try:
            c.publish(topic, payload, retain=retain)
        except Exception:
            pass

    def ack(self, cmd: str, ok: bool, msg: str = ""):
        payload = json.dumps({
            "cmd": cmd,
            "result": "OK" if ok else "ERROR",
            "msg": msg,
            "ts": int(time.time()),
        }, ensure_ascii=False)
        self.mqtt_publish(T_ACK, payload, retain=False)

    def publish_event(self, event_type: str, details: Optional[dict] = None):
        payload = json.dumps({
            "type": event_type,
            "timestamp": int(time.time()),
            "details": details or {},
        }, ensure_ascii=False)
        self.mqtt_publish(T_EVENT, payload, retain=False)

    def publish_health(self):
        h = self._health_dict()
        self.mqtt_publish(T_HEALTH, json.dumps({"health": h}, ensure_ascii=False), retain=False)

    def publish_status(self, force: bool = True):
        s = self.get_status()
        self.mqtt_publish(T_STATUS, json.dumps(s, ensure_ascii=False), retain=True if force else False)
        self.publish_health()

    def publish_diag(self):
        txt = self._build_diag_text()
        self.mqtt_publish(T_DIAG, json.dumps({"text": txt}, ensure_ascii=False), retain=False)

    def _build_diag_text(self) -> str:
        cfg = self._profile_cfg()
        lines = []
        lines.append("=== STREAM DIAGNOSTICS ===")
        lines.append(f"Time: {ts()}")
        lines.append(f"Mode: {self.state.mode.name}")
        lines.append(f"HTTP: {self.http.is_running()}")
        lines.append(f"Profile: {self.state.profile} ({cfg['w']}x{cfg['h']}@{cfg['fps']})")
        lines.append(f"URL (local): {LOCAL_STREAM_URL}")
        lines.append(f"HLS playlist: {HLS_PLAYLIST}")
        lines.append(f"Segments: {count_segments()}")
        lines.append("")
        h = self._health_dict()
        lines.append("=== HEALTH ===")
        for k in ["ssh", "camera", "ffmpeg", "http", "hls", "mqtt"]:
            lines.append(f"{k}: {h.get(k,'unknown')}")
        return "\n".join(lines)

    # ------------------- HEALTH -------------------

    def _health_dict(self) -> dict:
        pipeline_ok = self.pipeline.is_running()
        http_ok = self.http.is_running()
        mqtt_ok = self.state.mqtt_ok

        return {
            "engine_mode": self.state.mode.name.lower(),
            "engine": "healthy" if self.state.is_running() else ("transitioning" if self.state.is_starting() or self.state.mode.name in ["RESTARTING","STOPPING"] else "idle"),
            "pipeline": "healthy" if pipeline_ok else "failed",
        "http": "healthy" if http_ok else "failed",
        "mqtt": "healthy" if mqtt_ok else "failed",
        }

    # ------------------- PROFILE -------------------

    def _profile_cfg(self) -> dict:
        p = self.state.profile
        return PROFILES.get(p, PROFILES[DEFAULT_PROFILE])

    def set_profile(self, name: str) -> bool:
        name = (name or "").strip().lower()
        if name not in PROFILES:
            self.log(f"profile: invalid '{name}', allowed: {', '.join(PROFILES.keys())}")
            return False

        with self.lock:
            if self.state.profile == name:
                self.log(f"profile: already '{name}'")
                return True
            was_running = self.state.is_running()
            self.state.profile = name
            self.set_event("profile_set", "")

        self.log(f"profile: set -> {name}")

        # restart pipeline jeśli stream działa
        if was_running:
            self.log("profile: scheduling stream restart")
            threading.Thread(
                target=self._restart_stream_after_profile_change,
                daemon=True
            ).start()

        return True

    def _restart_stream_after_profile_change(self):
        self.state.set_mode(EngineMode.RESTARTING, event="stream_restarting")
        if self.restart_in_progress.is_set():
            self.log("profile restart already in progress")
            return

        self.restart_in_progress.set()
        try:
            self.log("profile restart: stopping stream")
            self.stop_stream()
            time.sleep(0.5)
            self.log("profile restart: starting stream")
            self.start_stream()
            self.publish_status(force=True)
        finally:
            self.restart_in_progress.clear()
            # state returns to RUNNING via start_stream() on success
            if not self.state.is_running():
                self.state.set_mode(EngineMode.IDLE, event="restart_failed")

# ------------------- STREAM CONTROL -------------------
    def start_stream(self) -> bool:
        with self.lock:
            if self.state.is_running():
                self.log("start_stream: already running")
                return True

            self.state.set_mode(EngineMode.STARTING, event="stream_starting")

        self.log(f"Starting stream (profile={self.state.profile})")

        # 1️⃣ start pipeline

        with self.lock:
            if not self.state.profile:
                self.state.profile = DEFAULT_PROFILE

        if not self.pipeline.start(self.state.profile):
            self.state.retry_count += 1
            self.log("start_stream: pipeline start FAILED")
            self.state.set_mode(EngineMode.ERROR, event="pipeline_start_failed", error="pipeline start failed")
            self.cleanup("pipeline_start_failed", "pipeline start failed")
            self.publish_status(force=True)
            return False

        # 2️⃣ start HTTP
        if not self.http.start():
            self.log("start_stream: http start FAILED")
            self.cleanup("http_start_failed", "http start failed")
            self.publish_status(force=True)
            return False

        # start MotionService worker (JEDEN RAZ) + SYNC FLAGS
        if self.state.motion_enabled:
            if not self.motion.is_running():
                self.motion.start()

        # 🔧 KLUCZOWE: synchronizacja akcji motion po starcie
            self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)

        # 3️⃣ mark running
        with self.lock:
            self.state.mark_stream_started()

        # 4️⃣ watchdog
        if not self.watchdog_thread or not self.watchdog_thread.is_alive():
            self.watchdog_thread = threading.Thread(
                target=self._watchdog_worker,
                daemon=True
            )
            self.watchdog_thread.start()

        self.publish_status(force=True)
        self.publish_event("stream_started", {
            "profile": self.state.profile,
            "url": self.get_public_stream_url()
        })

        self.log("STREAM OK")
        return True

    def stop_stream(self) -> bool:
        self.log("stop_stream requested")

        # allow stop from any mode incl. ERROR
        self.state.set_mode(EngineMode.STOPPING, event="stream_stopping")
        self.cleanup("stream_off", "", crash=False)
        self.state.set_mode(EngineMode.IDLE, event="stream_off")
        self.publish_status(force=True)
        self.publish_event("stream_stopped", {})
        return True

    def cleanup(self, reason: str, err: str, crash: bool = True):
        with self.lock:
            self.set_event(reason, err)
            if crash:
                self.state.crash_count += 1
                self.state.last_crash_at = time.time()
                self.state.set_mode(EngineMode.ERROR, event=reason, error=err)
            # always clear recording flags
            self.state.recording_active = False
            self.state.manual_recording = False

        self.log(f"cleanup: reason={reason} err={err!r}")

    # ZATRZYMANIE PIPELINE (JEDYNE MIEJSCE)
        self.pipeline.stop()
        try:
            self.motion.stop()
        except Exception:
            pass

    # 3️⃣ twardy fallback na Pi (na wypadek SSH zombie)
        try:
            kill_remote_rpicam()
        except Exception as e:
            self.log(f"cleanup: kill_remote_rpicam error: {e}")

        self.http.stop()

    def shutdown(self, reason="shutdown"):
        self.stop_event.set()
        self.cleanup(reason, "", crash=False)

    def _stop_proc(self, attr: str):
        p = getattr(self, attr, None)
        if not p:
            return

        try:
            self.log(f"cleanup: stopping {attr} pid={p.pid}")

            p.terminate()
            try:
                p.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self.log(f"cleanup: {attr} did not exit, killing")
                p.kill()
                p.wait(timeout=1.0)

        except Exception as e:
            self.log(f"cleanup: error stopping {attr}: {e}")

        finally:
            try:
                if p.stdout:
                    p.stdout.close()
            except Exception:
                pass

            try:
                if p.stderr:
                    p.stderr.close()
            except Exception:
                pass

            setattr(self, attr, None)

    # ------------------- WATCHDOG -------------------

    def _watchdog_worker(self):
        self.log("watchdog: started")
        while not self.stop_event.is_set():
            time.sleep(WATCHDOG_INTERVAL_SEC)

            if not self.state.is_running():
                # watchdog sleeps unless RUNNING
                continue

            if not self.pipeline.is_running():
                self.log("watchdog: pipeline not running")
                self.cleanup("pipeline_dead", "pipeline not running")
                self.publish_status(force=True)
                continue

            if not self.http.is_running():
                self.log("watchdog: http server not running")
                self.cleanup("http_dead", "http server not running")
                self.publish_status(force=True)
                continue
        self.log("watchdog: stopped")

# ------------------- PHOTO -------------------

    def take_photo(self):
        path = self.snapshot.take_photo()
        ok = path is not None
        self.ack("photo", ok, path or "failed")
        if ok:
            self.publish_event("photo_captured", {"path": path})
        self.publish_status(force=True)
        return path

    # ------------------- MOTION -------------------

    def set_motion(self, enabled: bool):
        with self.lock:
            self.state.motion_enabled = bool(enabled)
            self.set_event("motion_on" if enabled else "motion_off", "")

        try:
            if enabled:
                self.motion.set_enabled(True)
                self.motion.start()
            else:
                self.motion.set_enabled(False)
                self.motion.stop()
        except Exception as e:
            self.log(f"motion: service control error: {e!r}")

        self.publish_status(force=True)

    def set_motion_actions(self, photo: Optional[bool] = None, record: Optional[bool] = None):
        with self.lock:
            if photo is not None:
                self.state.motion_photo_enabled = bool(photo)
            if record is not None:
                self.state.motion_record_enabled = bool(record)

        # 🔴 KLUCZOWA LINIA – synchronizacja z MotionService
        self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)

        self.set_event("motion_actions", "")

        self.publish_status(force=True)

# ------------------- CLI (reader) -------------------

    def _cli_reader(self):
        sys.stdin = open("/dev/tty")
        """
        Czyta komendy z terminala i wrzuca je do kolejki.
        NIC nie wykonuje (bez _handle_cmd tutaj), bo input() ma nie blokować logiki silnika.
        """
        while not self.stop_event.is_set() and not self.cli_stop.is_set():
            try:
                cmdline = input("> ")
            except (EOFError, KeyboardInterrupt):
                # traktujemy jak "quit"
                self.cli_queue.put("quit")
                break

            if cmdline is None:
                continue

            cmdline = cmdline.strip()
            if not cmdline:
                continue

            # wrzuć do kolejki dla dispatchera
            self.cli_queue.put(cmdline)

            # jeśli user wpisał quit/exit, kończ readera
            if cmdline.lower() in ("q", "quit", "exit"):
                break

    def _on_motion_event(self, details: str):
        self.log(f"motion: DETECTED ({details})")

        with self.lock:
            do_photo = self.state.motion_photo_enabled
            do_record = self.state.motion_record_enabled
            self.set_event("motion_detected", details)

        self.log(f"motion: actions photo={do_photo} record={do_record}")

        self.publish_status(force=True)
        self.publish_event("motion_detected", {"details": details})

        if do_photo:
            threading.Thread(
                target=self.take_photo,
                daemon=True
            ).start()

        if do_record:
            # motion-based recording: nagrywaj dopóki jest ruch, stop po ciszy, rotate max 15 min
            self._last_motion_seen_ts = time.time()

            with self.lock:
                if self.state.recording_active:
                    self.log("motion: recording already active, extending")
                    return
                self.state.recording_active = True
                self.state.manual_recording = False

            def _rec():
                try:
                    from camera.config import AUTO_RECORD_MAX_SEC, AUTO_RECORD_IDLE_SEC

                    path = self.recorder.start_recording(seconds=None)
                    if path:
                        self.log(f"motion: recording started {path}")
                        with self.lock:
                            self.state.recordings_count += 1

                    start_ts = time.time()

                    while not self.stop_event.is_set():
                        with self.lock:
                            auto_enabled = self.state.motion_record_enabled
                            running = self.state.is_running()

                        if (not auto_enabled) or (not running):
                            break

                        last = getattr(self, "_last_motion_seen_ts", 0.0)
                        if time.time() - last >= AUTO_RECORD_IDLE_SEC:
                            break

                        if time.time() - start_ts >= AUTO_RECORD_MAX_SEC:
                            self.log("record: rotate (max length)")
                            self.recorder.stop_recording()
                            path = self.recorder.start_recording(seconds=None)
                            if path:
                                self.log(f"motion: recording continued {path}")
                                with self.lock:
                                    self.state.recordings_count += 1
                            start_ts = time.time()

                        time.sleep(0.5)

                    self.recorder.stop_recording()
                    self.log("record: finished (auto, motion ended)")

                except Exception as e:
                    self.log(f"motion: recording error: {e!r}")
                finally:
                    with self.lock:
                        self.state.recording_active = False
                        self.state.manual_recording = False
                    self.publish_status(force=True)

            threading.Thread(target=_rec, daemon=True).start()

# ------------------- TAILSCALE -------------------

    def tailscale_on(self) -> bool:
        self.log("tailscale: enabling")
        try:
            r = _run([TAILSCALE_BIN, "up"], timeout=15)
            if r.returncode == 0:
                self.set_event("tailscale_on", "")
                self.publish_status(force=True)
                return True
            self.set_event("tailscale_on_failed", r.stderr.strip())
            self.log(f"tailscale up error: {r.stderr.strip()}")
        except Exception as e:
            self.set_event("tailscale_on_failed", str(e))
            self.log(f"tailscale up exception: {e}")
        self.publish_status(force=True)
        return False

    def tailscale_off(self) -> bool:
        self.log("tailscale: disabling")
        try:
            r = _run([TAILSCALE_BIN, "down"], timeout=10)
            if r.returncode == 0:
                self.set_event("tailscale_off", "")
                self.publish_status(force=True)
                return True
            self.set_event("tailscale_off_failed", r.stderr.strip())
            self.log(f"tailscale down error: {r.stderr.strip()}")
        except Exception as e:
            self.set_event("tailscale_off_failed", str(e))
            self.log(f"tailscale down exception: {e}")
        self.publish_status(force=True)
        return False

    def get_public_stream_url(self) -> str:
        if tailscale_is_running():
            ip = tailscale_ip_v4()
            if ip:
                return f"http://{ip}:{TAILSCALE_PORT}/stream.m3u8"
        return f"http://127.0.0.1:{HTTP_PORT}/stream.m3u8"

    # ------------------- STATUS -------------------

    def get_status(self) -> dict:
        cfg = self._profile_cfg()
        with self.lock:
            stream_uptime = int(time.time() - self.state.stream_started_at) if self.state.stream_started_at else 0
            uptime = int(time.time() - self.state.started_at)
            features = {
                "motion_detection": self.state.motion_enabled,
                "manual_record": bool(self.state.manual_recording),
                "auto_record": self.state.motion_record_enabled,
                "motion_photo": self.state.motion_photo_enabled,
            }
            stats = {
                "photos_taken": self.state.photos_taken,
                "recordings_count": self.state.recordings_count,
                "segments_session": self.state.segments_session,
                "segments_total": count_segments(),
                "duration": stream_uptime,
                "crashes": self.state.crash_count,
                "retries": self.state.retry_count,
            }
            health = self._health_dict()
            net_mode = "tailscale" if tailscale_is_running() else "local"
            ts_ip = tailscale_ip_v4() if tailscale_is_running() else None

            return {
                "state": "active" if self.state.is_running() else "idle",
                "stream": self.state.is_running(),
                "http_ok": self.http.is_running(),
                "profile": self.state.profile,
                "resolution": f"{cfg['w']}x{cfg['h']}",
                "fps": cfg["fps"],
                "last_event": self.state.last_event,
                "last_error": self.state.last_error,
                "uptime_s": uptime,
                "stream_uptime_s": stream_uptime,
                "features": features,
                "stats": stats,
                "health": health,
                "network": {
                    "mode": net_mode,
                    "tailscale_ip": ts_ip,
                    "public_stream_url": self.get_public_stream_url(),
                },
                "local_stream_url": LOCAL_STREAM_URL,
                "hls_playlist": HLS_PLAYLIST,
            }

    # ========================= MQTT RX (UI -> ENGINE) =========================

    def _cmd_worker(self):
        self.log("cmd worker: started")
        while not self.stop_event.is_set():
            try:
                cmdline, source = self.cmd_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._handle_cmd(cmdline, source)
            except Exception as e:
                self.log(f"cmd worker error: {e!r}")
        self.log("cmd worker: stopped")

    def _mqtt_worker(self):
        self.log("mqtt worker: started")
        while not self.stop_event.is_set() and not self.mqtt_stop_event.is_set():
            time.sleep(0.5)
        self.log("mqtt worker: stopped")

    def _is_cmd_allowed(self, cmd: str) -> bool:
        mode = self.state.mode
        if cmd in ("start","stream_on"):
            return mode in (EngineMode.IDLE,)
        if cmd in ("stop","stream_off"):
            return mode in (EngineMode.RUNNING, EngineMode.STARTING)
        if cmd in ("low","med","high") or cmd.startswith("profile"):
            return mode in (EngineMode.RUNNING, EngineMode.IDLE)
        if cmd in ("status","diag","photo","tailscale_status"):
            return True
        # domyślnie pozwalamy
        return True

    def _handle_cmd(self, cmdline: str, source: str = "mqtt"):
        raw = (cmdline or "").strip()
        cmd = raw.lower()
        if not self._is_cmd_allowed(cmd):
            self.log(f"cmd rejected by mode={self.state.mode.name}: {cmd}")
            self.ack(cmd, False, f"rejected in mode {self.state.mode.name}")
            return

        if not cmd:
            return

        # UI spamuje diag/status? OK. To obsługujemy lekko i bez restartów.

        if cmd in ("status",):
            # MQTT status zawsze publikujemy
            self.publish_status(force=True)
            self.ack("status", True, "ok")

            # CLI ma też coś zobaczyć lokalnie
            if source == "cli":
                try:
                    print(json.dumps(self.get_status(), ensure_ascii=False, indent=2), flush=True)
                except Exception as e:
                    print(f"[status] print error: {e}", flush=True)
            return

        if cmd in ("diag",):
            self.publish_diag()
            self.ack("diag", True, "ok")
            return

        if cmd in ("stream_on", "start"):
            ok = self.start_stream()
            self.ack("stream_on", ok, "started" if ok else "failed")
            return

        if cmd in ("stream_off", "stop"):
            ok = self.stop_stream()
            self.ack("stream_off", ok, "stopped")
            return

        if cmd == "photo":
            path = self.take_photo()
            ok = path is not None
            self.ack("photo", ok, path or "failed")
            return

        if cmd in ("rec_on", "record_on"):
            with self.lock:
                if self.state.recording_active:
                    self.ack("rec_on", False, "recording already active")
                    return
                self.state.recording_active = True
                self.state.manual_recording = True
            path = self.recorder.start_recording()
            ok = path is not None
            if ok:
                with self.lock:
                    self.state.recordings_count += 1
            else:
                with self.lock:
                    self.state.recording_active = False
                    self.state.manual_recording = False
            self.ack("rec_on", ok, path or "failed")
            return

        if cmd in ("rec_off", "record_off"):
            ok = self.recorder.stop_recording()
            still = self.recorder.is_recording()
            with self.lock:
                self.state.manual_recording = False
                self.state.recording_active = bool(still)
            self.ack("rec_off", ok, "stopped")
            return

        if cmd == "motion_on":

            self.set_motion(True)

            try:

                self.state.motion_enabled = True

            except Exception:

                pass

            try:

                self._save_state()

            except Exception:

                pass

            self.ack("motion_on", True, "on")

            try:
                self.state.motion_enabled = True
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass
            try:
                self._save_state()
            except Exception:
                pass
            if source == "cli":

                print("OK: motion_detection ON", flush=True)

            return

        if cmd == "motion_off":

            self.set_motion(False)

            try:

                self.state.motion_enabled = False

            except Exception:

                pass

            try:

                self._save_state()

            except Exception:

                pass

            self.ack("motion_off", True, "off")

            try:
                self.state.motion_enabled = False
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass
            try:
                self._save_state()
            except Exception:
                pass
            if source == "cli":

                print("OK: motion_detection OFF", flush=True)

            return

        if cmd in ("mphoto_on", "motion_photo_on"):

            self.set_motion_actions(photo=True)

            try:

                self.state.motion_photo_enabled = True

                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)

            except Exception:

                pass

            try:

                self._save_state()

            except Exception:

                pass

            self.ack("mphoto_on", True, "on")

            try:
                self.state.motion_photo_enabled = True
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass
            try:
                self._save_state()
            except Exception:
                pass
            if source == "cli":

                print("OK: motion_photo ON", flush=True)

            return

        if cmd in ("mphoto_off", "motion_photo_off"):

            self.set_motion_actions(photo=False)

            try:

                self.state.motion_photo_enabled = False

                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)

            except Exception:

                pass

            try:

                self._save_state()

            except Exception:

                pass

            self.ack("mphoto_off", True, "off")

            try:
                self.state.motion_photo_enabled = False
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass
            try:
                self._save_state()
            except Exception:
                pass
            if source == "cli":

                print("OK: motion_photo OFF", flush=True)

            return

        if cmd in ("mrec_on", "rec_motion_on"):

            self.set_motion_actions(record=True)

            try:

                self.state.motion_record_enabled = True

                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)

            except Exception:

                pass

            try:

                self._save_state()

            except Exception:

                pass

            self.ack("mrec_on", True, "on")

            try:
                self.state.motion_record_enabled = True
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass
            try:
                self._save_state()
            except Exception:
                pass
            if source == "cli":

                print("OK: auto_record ON", flush=True)

            return

        if cmd in ("mrec_off", "rec_motion_off"):

            self.set_motion_actions(record=False)

            try:

                self.state.motion_record_enabled = False

                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)

            except Exception:

                pass

            try:

                self._save_state()

            except Exception:

                pass

            self.ack("mrec_off", True, "off")

            try:
                self.state.motion_record_enabled = False
                self.motion.set_actions(self.state.motion_photo_enabled, self.state.motion_record_enabled)
            except Exception:
                pass
            try:
                self._save_state()
            except Exception:
                pass
            if source == "cli":

                print("OK: auto_record OFF", flush=True)

            return

        if cmd in ("low", "med", "high"):
            ok = self.set_profile(cmd)
            self.ack(cmd, ok, "ok" if ok else "failed")
            return


            try:

                self._save_state()

            except Exception:

                pass

            if source == "cli":

                try:

                    print("OK: profile changed", flush=True)

                except Exception:

                    pass

            return

        if cmd.startswith("profile "):
            parts = cmd.split()
            if len(parts) == 2:
                ok = self.set_profile(parts[1])
                self.ack("profile", ok, parts[1])
            else:
                self.ack("profile", False, "usage: profile low|med|high")
            return


            try:

                self._save_state()

            except Exception:

                pass

            if source == "cli":

                try:

                    print("OK: profile set", flush=True)

                except Exception:

                    pass

            return

        if cmd == "tailscale_on":
            ok = self.tailscale_on()
            self.ack("tailscale_on", ok, "ok" if ok else "failed")
            return

        if cmd == "tailscale_off":
            ok = self.tailscale_off()
            self.ack("tailscale_off", ok, "ok" if ok else "failed")
            return

        if cmd == "tailscale_status":
            mode = "ON" if tailscale_is_running() else "OFF"
            ip = tailscale_ip_v4()
            url = self.get_public_stream_url()
            msg = f"{mode} ip={ip} url={url}"

            self.publish_status(force=True)
            self.ack("tailscale_status", True, msg)

            if source == "cli":
                print(msg, flush=True)
            return
        self.ack(raw, False, "unknown command")

    def mqtt_start(self):
        if self.mqtt_client:
            return

        c = mqtt.Client()
        self.mqtt_client = c

        def on_connect(client, userdata, flags, rc, properties=None):
            with self.lock:
                self.state.mqtt_ok = True
            self.log("mqtt: connected")
            client.subscribe(T_CMD)
            self.publish_status(force=True)
            self.publish_diag()
            self.publish_health()

        def on_disconnect(client, userdata, rc, properties=None):
            with self.lock:
                self.state.mqtt_ok = False
            self.log("mqtt: disconnected")

        def on_message(client, userdata, msg):
            try:
                payload = msg.payload.decode(errors="ignore").strip()
            except Exception:
                payload = ""

            if payload:
                self.cmd_queue.put((payload,"mqtt"))

        c.on_connect = on_connect
        c.on_disconnect = on_disconnect
        c.on_message = on_message

        c.connect(MQTT_BROKER, MQTT_PORT)
        c.loop_start()

        if not self.mqtt_thread or not self.mqtt_thread.is_alive():
            self.mqtt_thread = threading.Thread(
                target=self._mqtt_worker,
                daemon=True
            )
            self.mqtt_thread.start()

    def mqtt_stop(self):
        c = self.mqtt_client
        if not c:
            return

        self.mqtt_stop_event.set()
        try:
            c.loop_stop()
            c.disconnect()
        except Exception:
            pass

        self.mqtt_client = None
        with self.lock:
            self.state.mqtt_ok = False

ENGINE = StreamEngine()

def _handle_signal(sig, _frame):
    ENGINE.log(f"signal: {sig} -> shutdown")
    ENGINE.shutdown("signal")
    try:
        ENGINE._save_state()
    except Exception:
        pass
    try:
        ENGINE.mqtt_stop()
    except Exception:
        pass
    sys.exit(0)


def _is_foreground():
    import sys
    try:
        stdin_ok = bool(getattr(sys.stdin, 'isatty', lambda: False)())
        stdout_ok = bool(getattr(sys.stdout, 'isatty', lambda: False)())
        return stdin_ok and stdout_ok
    except Exception:
        return False


def main():
    import signal, sys
    if not _is_foreground():
        signal.signal(signal.SIGTTOU, signal.SIG_IGN)
        signal.signal(signal.SIGTTIN, signal.SIG_IGN)
        signal.signal(signal.SIGTSTP, signal.SIG_IGN)
    ensure_dirs()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    ENGINE.log("stream_engine_v5: start")
    ENGINE.log("Commands (CLI): start | stop | photo | rec_on | rec_off | motion_on | motion_off | mphoto_on/off | mrec_on/off | status | diag | profile low|med|high | low|med|high | tailscale_on | tailscale_off | tailscale_status | quit")
    ENGINE.log(f"MQTT: sub {T_CMD} (UI -> engine), pub {T_STATUS},{T_ACK},{T_LOG},{T_DIAG},{T_HEALTH},{T_EVENT}")

    # MQTT działa równolegle do sterowania z CLI
    ENGINE.mqtt_start()

    ENGINE.cmd_worker_thread = threading.Thread(target=ENGINE._cmd_worker, daemon=True)
    ENGINE.cmd_worker_thread.start()
    # CLI: TTY = interaktywnie, PIPE = heredoc (też ma działać)
    try:
        stdin_ok = (hasattr(sys, "stdin") and sys.stdin and (not getattr(sys.stdin, "closed", True)))
    except Exception:
        stdin_ok = False

    if stdin_ok:
        cli_thread = threading.Thread(
            target=ENGINE._cli_reader,
            daemon=True
        )
        cli_thread.start()
        if not _is_foreground():
            ENGINE.log("CLI: stdin pipe mode")
    else:
        ENGINE.log("CLI disabled (stdin closed)")
    while not ENGINE.stop_event.is_set():
        try:
            cmdline = ENGINE.cli_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        if not cmdline:
            continue

        cmd = cmdline.lower()

        if cmd in ("q", "quit", "exit"):
            ENGINE.shutdown("quit")
            try:
                ENGINE._save_state()
            except Exception:
                pass
            ENGINE.mqtt_stop()
            break

        ENGINE.cmd_queue.put((cmdline,"cli"))



if __name__ == "__main__":
    main()
