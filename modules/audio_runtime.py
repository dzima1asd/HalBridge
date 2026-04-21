import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from modules.voice_runtime_state import load_runtime_status, save_runtime_status


JBL_MAC = "04:21:44:BC:5C:EB"
JBL_SINK = "bluez_sink.04_21_44_BC_5C_EB.a2dp_sink"
DEFAULT_SINK = "alsa_output.pci-0000_00_1b.0.analog-stereo"

VOICE_PYTHON = "/home/hal/venvs/halvoice/bin/python"
VOICE_ARGS = ["-m", "modules.voice_runtime"]
VOICE_ROOT = Path("/home/hal/HALbridge")
VOICE_LOG_DIR = VOICE_ROOT / "logs"
VOICE_STATE_DIR = VOICE_ROOT / "state"
VOICE_PID_FILE = VOICE_STATE_DIR / "voice_runtime.pid"
VOICE_LOG_FILE = VOICE_LOG_DIR / "voice_runtime.log"


def _read_voice_pid() -> int | None:
    try:
        raw = VOICE_PID_FILE.read_text(encoding="utf-8").strip()
        return int(raw) if raw else None
    except Exception:
        return None


def _is_pid_running(pid: int | None) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _clear_voice_pid() -> None:
    try:
        if VOICE_PID_FILE.exists():
            VOICE_PID_FILE.unlink()
    except Exception:
        pass


def _voice_running() -> tuple[bool, int | None]:
    pid = _read_voice_pid()
    if _is_pid_running(pid):
        return True, pid
    if pid is not None:
        _clear_voice_pid()
    return False, None


def _voice_start() -> tuple[bool, str]:
    running, pid = _voice_running()
    if running:
        return True, f"🎙️ Voice już działa w tle (PID {pid})"

    VOICE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_STATE_DIR.mkdir(parents=True, exist_ok=True)

    logf = open(VOICE_LOG_FILE, "ab", buffering=0)
    try:
        proc = subprocess.Popen(
            [VOICE_PYTHON, *VOICE_ARGS],
            cwd=str(VOICE_ROOT),
            stdout=logf,
            stderr=logf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        logf.close()
        raise

    VOICE_PID_FILE.write_text(str(proc.pid), encoding="utf-8")
    return True, f"🎙️ Voice włączony w tle (PID {proc.pid})"



def _reset_voice_runtime_state() -> None:
    try:
        st = load_runtime_status()
        st["current_state"] = "idle"
        st["tts_active"] = False
        st["tts_source"] = None
        st["listening_blocked"] = False
        st["block_reason"] = None
        st["speaker_auto_on_done"] = False
        if st.get("last_error") == "listening_blocked:tts":
            st["last_error"] = None
        save_runtime_status(st)
    except Exception:
        pass



def _set_voice_start_grace(seconds: float = 2.0) -> None:
    try:
        st = load_runtime_status()
        st["listening_blocked"] = True
        st["block_reason"] = "voice_start_grace"
        st["current_state"] = "idle"
        save_runtime_status(st)
    except Exception:
        return

    def _clear_later():
        time.sleep(seconds)
        try:
            st2 = load_runtime_status()
            if st2.get("block_reason") == "voice_start_grace":
                st2["listening_blocked"] = False
                st2["block_reason"] = None
                save_runtime_status(st2)
        except Exception:
            pass

    try:
        threading.Thread(target=_clear_later, daemon=True).start()
    except Exception:
        pass


def _voice_stop() -> tuple[bool, str]:
    running, pid = _voice_running()
    if not running:
        _reset_voice_runtime_state()
        return True, "🛑 Voice już był wyłączony."

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        _clear_voice_pid()
        _reset_voice_runtime_state()
        return True, "🛑 Voice był już zatrzymany."

    for _ in range(20):
        if not _is_pid_running(pid):
            _clear_voice_pid()
            _reset_voice_runtime_state()
            return True, "🛑 Voice wyłączony."
        time.sleep(0.1)

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass

    time.sleep(0.1)
    _clear_voice_pid()
    _reset_voice_runtime_state()
    return True, "🛑 Voice wyłączony (SIGKILL)."


def handle_audio_runtime(line: str):
    low = (line or "").strip().lower()

    if low == "voice on":
        ok, msg = _voice_start()
        if ok:
            _set_voice_start_grace(5.0)
        return ok, msg

    if low == "voice off":
        ok, msg = _voice_stop()
        return ok, msg

    if low == "jbl on":
        subprocess.run(
            ["bluetoothctl", "connect", JBL_MAC],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

        sinks = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True,
            text=True,
            check=False,
        )
        if JBL_SINK not in (sinks.stdout or ""):
            return True, "❌ JBL nie jest połączony jako sink audio."

        rc = subprocess.run(
            ["pactl", "set-default-sink", JBL_SINK],
            check=False,
        ).returncode

        if rc == 0:
            return True, "🔊 Audio przełączone na JBL Charge 4"
        return True, "❌ Nie udało się przełączyć audio na JBL."

    if low == "jbl off":
        rc = subprocess.run(
            ["pactl", "set-default-sink", DEFAULT_SINK],
            check=False,
        ).returncode

        subprocess.run(
            ["bluetoothctl", "disconnect", JBL_MAC],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if rc == 0:
            return True, "🔈 Audio przełączone na głośnik standardowy"
        return True, "❌ Nie udało się przełączyć audio na głośnik standardowy."

    return False, None
