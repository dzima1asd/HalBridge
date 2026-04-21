from __future__ import annotations

import os
import shlex
import stat
import time
from pathlib import Path


def analyze_codegen_prompt(prompt: str, intelligence_module=None):
    analysis = {"type": "text", "profile": "headless", "expected_output": "tekst"}
    task_meta = None
    profile = "headless"
    expected_output = None
    task_type = "text"

    if intelligence_module:
        try:
            analysis = intelligence_module.analyze_prompt(prompt)
            task_type = analysis["type"]
            profile = analysis["profile"]
            expected_output = analysis["expected_output"]
            print(f"[INTELIGENCE] typ={task_type}, profil={profile}, wynik={expected_output}")
        except Exception as e:
            print(f"[INTELIGENCE] błąd analizy: {e}")

        try:
            task_meta = intelligence_module.analyze_prompt(prompt)
            profile = task_meta.get("profile", "headless")
            expected_output = task_meta.get("expected_output")
            task_type = task_meta.get("type")
            print(f"[INTELLIGENCE] Typ: {task_type}, Profil: {profile}, Cel: {expected_output}")
        except Exception as e:
            print(f"[INTELLIGENCE] Błąd analizy promptu: {e}")
            profile = "headless"
            expected_output = None

    return {
        "analysis": analysis,
        "task_meta": task_meta,
        "profile": profile,
        "expected_output": expected_output,
        "task_type": task_type,
    }


def build_codegen_filename(filename: str | None) -> str:
    if filename:
        return filename
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"ai_code_{ts}.py"


def build_run_command(abs_target: Path) -> str | None:
    low = str(abs_target).lower()
    if low.endswith(".py"):
        return f"python3 {shlex.quote(str(abs_target))}"
    if low.endswith((".sh", ".bash")):
        try:
            st = os.stat(abs_target)
            os.chmod(abs_target, st.st_mode | stat.S_IEXEC)
        except Exception:
            pass
        return f"bash {shlex.quote(str(abs_target))}"
    return None


def register_generated_code(abs_target: Path, active_project, last_task_meta, code_registry_module=None):
    if not code_registry_module:
        return

    if not abs_target or not os.path.exists(abs_target):
        return

    try:
        rec = code_registry_module.register_path(
            abs_target,
            project=(active_project or "sandbox"),
            meta=last_task_meta
        )
        print(f"[REGISTRY] Zarejestrowano plik: {rec['file']} (SHA256={rec['sha256'][:8]})")
        code_registry_module.git_autocommit(
            os.path.relpath(abs_target, Path.home() / "HALbridge"),
            f"auto: code generated {rec['project']}"
        )
    except Exception as e:
        print(f"[REGISTRY] Błąd rejestracji: {e}")
