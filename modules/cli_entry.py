import json
import select
import sys
import os
import subprocess
import threading
import time
from pathlib import Path
from datetime import datetime, timezone as tz

from modules.cam_pi import handle_camera_command
from modules.cli_kernel_bridge import (
    cli_result_to_printable,
    execute_cli_fallback,
    execute_cli_hardware,
)
from modules.cli_about_runtime import handle_about_runtime
from modules.cli_basic_dispatch import handle_basic_cli
from modules.cli_browser_runtime import handle_browser_runtime
from modules.cli_browser_yt_runtime import handle_browser_yt_runtime
from modules.cli_core_dispatch import handle_core_dispatch
from modules.cli_explicit_dispatch import handle_explicit_dispatch
from modules.cli_files_runtime import handle_files_runtime
from modules.cli_http_runtime import handle_http_runtime
from modules.cli_logs_runtime import handle_logs_runtime
from modules.cli_memory_runtime import handle_memory_runtime
from modules.cli_module_runtime import handle_module_runtime
from modules.cli_project_runtime import handle_project_runtime
from modules.cli_runtime_controls import handle_runtime_controls
from modules.cli_runtime_meta import handle_runtime_meta
from modules.cli_tokens_runtime import handle_tokens_runtime
from modules.cli_vcs_runtime import handle_vcs_runtime
from modules.codegen_utils import PROMPT_RULES_FILE
from modules.audio_runtime import handle_audio_runtime



VOICE_STATUS_PATH = Path("/home/hal/HALbridge/state/voice_runtime_status.json")
VOICE_COMMAND_QUEUE_PATH = Path("/home/hal/HALbridge/state/voice_command_queue.jsonl")


def _drain_voice_command_queue() -> list[str]:
    try:
        if not VOICE_COMMAND_QUEUE_PATH.exists():
            return []
        raw = VOICE_COMMAND_QUEUE_PATH.read_text(encoding="utf-8")
        VOICE_COMMAND_QUEUE_PATH.write_text("", encoding="utf-8")
    except Exception:
        return []

    out: list[str] = []
    for line in raw.splitlines():
        row = (line or "").strip()
        if not row:
            continue
        try:
            obj = json.loads(row)
        except Exception:
            continue
        cmd = str(obj.get("command") or "").strip()
        if cmd:
            out.append(cmd)
    return out



def _voice_report_monitor() -> None:
    last_status_sig = None
    last_heard = None
    last_action = None
    last_reply = None
    last_error = None

    while True:
        try:
            if VOICE_STATUS_PATH.exists():
                obj = json.loads(VOICE_STATUS_PATH.read_text(encoding="utf-8"))
                current_state = (obj.get("current_state") or "").strip()
                transcript = (obj.get("last_transcript") or "").strip()
                action_taken = (obj.get("action_taken") or "").strip()
                reply_text = (obj.get("last_reply_text") or "").strip()
                last_error_text = (obj.get("last_error") or "").strip()
                listening_blocked = bool(obj.get("listening_blocked", False))
                block_reason = (obj.get("block_reason") or "").strip()
                ts = ((obj.get("timestamps") or {}).get("updated_at")) or ""

                if listening_blocked and block_reason == "voice_start_grace":
                    time.sleep(0.6)
                    continue

                status_sig = (ts, current_state, transcript, action_taken, reply_text, last_error_text)
                if status_sig != last_status_sig:
                    last_status_sig = status_sig

                    if (
                        last_error_text
                        and last_error_text != last_error
                        and last_error_text not in (
                            "empty_transcript",
                            "listening_blocked:tts",
                            "listening_blocked:voice_start_grace",
                        )
                    ):
                        last_error = last_error_text
                        print(f"\n🎙️ voice error: {last_error_text}")

                    if transcript and transcript != last_heard and action_taken != "cooldown":
                        last_heard = transcript
                        print(f'\n🎙️ voice heard: "{transcript}"')

                    if action_taken and action_taken != "cooldown" and action_taken != last_action:
                        last_action = action_taken
                        print(f"🎙️ voice action: {action_taken}")

                    if reply_text and action_taken != "cooldown" and reply_text != last_reply:
                        last_reply = reply_text
                        short_reply = reply_text.replace("\n", " ").strip()
                        if len(short_reply) > 220:
                            short_reply = short_reply[:217] + "..."
                        print(f"🎙️ voice reply: {short_reply}")
        except Exception:
            pass

        time.sleep(0.6)


def confirm(msg: str) -> bool:
    try:
        ans = input(f"{msg} Wykonać? [y/N] ").strip().lower()
        return ans == "y"
    except EOFError:
        print("\n👋 Do zobaczenia (EOF).")
        return False
    except KeyboardInterrupt:
        print("\n⏹️ Przerwano.")
        return False



def _kill_process_names(names: list[str]) -> list[str]:
    killed = []
    for name in names:
        try:
            rc = subprocess.run(
                ["pkill", "-f", name],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            if rc == 0:
                killed.append(name)
        except Exception:
            pass
    return killed


def _shutdown_agent_io(bridge) -> list[str]:
    reports = []

    try:
        handled, msg = handle_audio_runtime("voice off")
        if handled and msg:
            reports.append(msg)
    except Exception as e:
        reports.append(f"[voice off error] {type(e).__name__}: {e}")

    try:
        hw_result = bridge.execute("wylacz glosnik")
        if hw_result:
            reports.append(hw_result)
        else:
            reports.append("🔇 Próba wyłączenia głośnika przez Shelly nie zwróciła komunikatu.")
    except Exception as e:
        reports.append(f"[speaker off error] {type(e).__name__}: {e}")

    killed = _kill_process_names([
        "arecord",
        "ffmpeg",
        "rpicam-vid",
        "libcamera-vid",
        "gst-launch-1.0",
    ])
    if killed:
        reports.append("📷/🎤 Zatrzymane procesy AV: " + ", ".join(killed))

    return reports


def run_cli(api, cfg, browser, bridge, registry):
    try:
        handled, audio_out = handle_audio_runtime("voice on")
        if VOICE_STATUS_PATH.exists():
            try:
                obj = json.loads(VOICE_STATUS_PATH.read_text(encoding="utf-8"))
                obj["last_transcript"] = ""
                obj["last_reply_text"] = ""
                obj["last_error"] = None
                obj["action_taken"] = ""
                VOICE_STATUS_PATH.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
        if handled and audio_out:
            print(audio_out)
    except Exception as e:
        print(f"[VOICE AUTOSTART ERROR] {type(e).__name__}: {e}")

    try:
        threading.Thread(target=_voice_report_monitor, daemon=True).start()
    except Exception as e:
        print(f"[VOICE REPORT MONITOR ERROR] {type(e).__name__}: {e}")

    prompt_shown = False
    while True:
        try:
            _voice_queue = _drain_voice_command_queue()
            from_voice_queue = False
            if _voice_queue:
                line = _voice_queue[0].strip()
                from_voice_queue = True
            else:
                if not prompt_shown:
                    print("hal@agent:~$ ", end="", flush=True)
                    prompt_shown = True
                ready, _, _ = select.select([sys.stdin], [], [], 0.5)
                if not ready:
                    continue
                line = sys.stdin.readline().strip()
                prompt_shown = False

            if not line:
                continue

            low = line.lower()

            if low.startswith("zapamiętaj "):
                text = line[len("zapamiętaj "):].strip()
                if not text:
                    print("⚠ Brak treści do zapamiętania.")
                    continue
                try:
                    os.makedirs(os.path.dirname(PROMPT_RULES_FILE), exist_ok=True)
                    with open(PROMPT_RULES_FILE, "a", encoding="utf-8") as f:
                        f.write(text + "\n")
                    print("✅ Zapamiętane jako stała reguła systemowa.")
                except Exception as e:
                    print(f"❌ Nie udało się zapisać reguły: {e}")
                continue

            hw = execute_cli_hardware(line)
            if hw.get("handled"):
                print(cli_result_to_printable(hw))
                continue

            if from_voice_queue:
                voice_local_line = line
                low_voice_local = voice_local_line.lower().strip()
                if low_voice_local.startswith("youtube "):
                    voice_local_line = "yt " + voice_local_line.split(" ", 1)[1].strip()

                yt_handled, yt_out = handle_browser_yt_runtime(voice_local_line, browser)
                if yt_handled:
                    if yt_out:
                        print(yt_out)
                    continue

                handled, browser_out = handle_browser_runtime(voice_local_line, browser, registry)
                if handled:
                    if browser_out:
                        print(browser_out)
                    continue

                fallback_yt_line = f"yt {line.strip()}".strip()
                yt_handled, yt_out = handle_browser_yt_runtime(fallback_yt_line, browser)
                if yt_handled:
                    if yt_out:
                        print(yt_out)
                    continue

                print("🎙️ Pominięto komendę voice bez lokalnego dopasowania.")
                continue

            cam = handle_camera_command(line)
            if cam is not None:
                print(cam)
                continue

            handled, module_out = handle_module_runtime(line, api)
            if handled:
                if module_out:
                    print(module_out)
                continue

            handled, project_out = handle_project_runtime(line, api)
            if handled:
                if project_out:
                    print(project_out)
                continue

            handled, tokens_out = handle_tokens_runtime(line, api)
            if handled:
                if tokens_out:
                    print(tokens_out)
                continue

            handled, about_out = handle_about_runtime(line, cfg)
            if handled:
                if about_out:
                    print(about_out)
                continue

            handled, http_out = handle_http_runtime(line, api)
            if handled:
                if http_out:
                    print(http_out)
                continue

            handled, file_out = handle_files_runtime(line, api)
            if handled:
                if file_out:
                    print(file_out)
                continue

            handled, mem_out = handle_memory_runtime(line, api)
            if handled:
                if mem_out:
                    print(mem_out)
                continue

            handled, logs_out = handle_logs_runtime(line, api, cfg)
            if handled:
                if logs_out:
                    print(logs_out)
                continue

            handled, vcs_out = handle_vcs_runtime(line, api)
            if handled:
                if vcs_out:
                    print(vcs_out)
                continue

            handled, audio_out = handle_audio_runtime(line)
            if handled:
                if audio_out:
                    print(audio_out)
                continue

            if line and set(line.strip()) == {"+"}:
                yt_handled, yt_out = handle_browser_yt_runtime(line, browser)
                if yt_handled:
                    if yt_out:
                        print(yt_out)
                    continue

            try:
                handled, output, show_meter = handle_core_dispatch(line, api)
                if handled:
                    if output is not None:
                        print(output)
                    if show_meter:
                        try:
                            print(api.meter.summary())
                        except Exception:
                            pass
                    continue
            except Exception as e:
                print(f"[CORE ERROR] {type(e).__name__}: {e}")
                continue

            handled, basic_out, should_break = handle_basic_cli(line)
            if handled:
                if basic_out:
                    print(basic_out)
                if should_break:
                    for _msg in _shutdown_agent_io(bridge):
                        print(_msg)
                    break
                continue

            handled, meta_out = handle_runtime_meta(line, api, cfg)
            if handled:
                if meta_out:
                    print(meta_out)
                continue

            handled, ctrl_out = handle_runtime_controls(line, cfg, api)
            if handled:
                if ctrl_out:
                    print(ctrl_out)
                continue

            yt_handled, yt_out = handle_browser_yt_runtime(line, browser)
            if yt_handled:
                if yt_out:
                    print(yt_out)
                continue

            handled, browser_out = handle_browser_runtime(line, browser, registry)
            if handled:
                if browser_out:
                    print(browser_out)
                continue

            if line.startswith("!"):
                cmd = line[1:]
                ok, warn = api.validator.validate(cmd)
                if not ok:
                    print(warn or "❌ Komenda zablokowana.")
                    continue
                if warn:
                    if not confirm(f"⚠️ {warn}. To może być ryzykowne."):
                        try:
                            with open(cfg.RUN_ERR_FILE, "a", encoding="utf-8") as f:
                                f.write(
                                    f"[{datetime.now(tz=tz.utc).isoformat(timespec='seconds')}] "
                                    f"WARN-SKIP: {warn} for: {cmd}\n---\n"
                                )
                        except Exception:
                            pass
                        print("⏭️ Pominięto.")
                        continue

                hw_result = bridge.execute(cmd)
                if hw_result:
                    print(hw_result)
                    continue

                success, out = api.exec.run(cmd, warn=warn)
                print(out)
                continue

            handled, explicit_out, explicit_show_meter = handle_explicit_dispatch(line, api)
            if handled:
                if explicit_out:
                    print(explicit_out)
                if explicit_show_meter:
                    try:
                        print(api.meter.summary())
                    except Exception:
                        pass
                continue

            if cfg.STRICT_MODE and False:
                cmd = line
                ok, warn = api.validator.validate(cmd)
                if not ok:
                    print(warn or "❌ Komenda zablokowana.")
                    continue
                if warn:
                    print(warn)
                    if not confirm("To może być ryzykowne. Wykonać?"):
                        print("⏭️ Pominięto.")
                        continue
                success, out = api.exec.run(cmd)
                print(out)
                continue

            fallback = execute_cli_fallback(line)
            print(cli_result_to_printable(fallback))
            print(api.meter.summary())

        except KeyboardInterrupt:
            print("\n⏹️ Przerwano. 'exit' aby zakończyć.")
        except EOFError:
            print("\n👋 Do zobaczenia (EOF).")
            for _msg in _shutdown_agent_io(bridge):
                print(_msg)
            break
        except Exception as e:
            print(f"❌ Błąd: {e}")
