from __future__ import annotations
# Subsystem !py przeniesiony z gpt_chat_v4.py

def handle_console_line_py_mode(line: str) -> str | None:
    s = line.strip()
    if not s.startswith("!py-mode"):
        return None
    parts = shlex.split(s)
    if len(parts) == 1:
        return f"[PY] Tryb: {GLOBAL_PY_EXEC_MODE} (użyj: !py-mode interactive | capture)"
    mode = parts[1].lower()
    if mode not in ("interactive", "capture"):
        return "[PY] Nieznany tryb. Dozwolone: interactive, capture"
    globals()["GLOBAL_PY_EXEC_MODE"] = mode
    return f"[PY] Ustawiono tryb na: {mode}"


def _is_path_allowed(path: str) -> bool:
    try:
        p = pathlib.Path(path).resolve()
        for base in PY_ALLOW_DIRS:
            if p.is_relative_to(pathlib.Path(base).resolve()):
                return True
    except Exception:
        pass
    return False


def _preexec_resource_limits():
    # RAM
    resource.setrlimit(resource.RLIMIT_AS, (PY_RAM_LIMIT_MB * 1024 * 1024, PY_RAM_LIMIT_MB * 1024 * 1024))
    # CPU
    resource.setrlimit(resource.RLIMIT_CPU, (PY_CPU_SECS, PY_CPU_SECS))


def run_python_script(script_path: str, args: list[str]) -> dict:
    # 1) Prefer sandbox if available
    if 'code_sandbox' in globals() and code_sandbox:
        try:
            res = code_sandbox.run_file(script_path, profile=None)
            # --- analiza wyniku (opcjonalnie) ---
            try:
                from modules import result_analyzer as _ra
                summary = _ra.analyze_result(res, None)
                _ra.log_result(res, None)
                print(f"[RESULT] {summary}")
            except Exception:
                pass
            return {
                "ok": bool(res.get("ok")),
                "msg": f"[PY] Exit={res.get('returncode')}, job=sandbox",
                "stdout": (res.get("stdout") or "")[:PY_STDOUT_MAX],
                "stderr": (res.get("stderr") or "")[:PY_STDOUT_MAX],
                "job": res.get("job"),
                "dir": res.get("dir"),
                "cmd": res.get("cmd"),
            }
        except Exception:
            pass
    if not os.path.exists(script_path):
        return {"ok": False, "msg": f"[PY] Nie znaleziono pliku: {script_path}"}
    if not _is_path_allowed(script_path):
        return {"ok": False, "msg": f"[PY] Niedozwolona ścieżka: {script_path}"}

    job_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    job_dir = os.path.join(JOBS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    python_bin = PYTHON_VENV if os.path.exists(PYTHON_VENV) else "python3"
    cmd = [python_bin, script_path] + args
    cwd = os.path.dirname(os.path.abspath(script_path)) or "/"

    mode = globals().get("GLOBAL_PY_EXEC_MODE", "interactive")

    try:
        if mode == "interactive":
            # Uruchomienie na żywo, wyjście idzie wprost do terminala
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                preexec_fn=_preexec_resource_limits,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
            return {"ok": True, "msg": f"[PY] Uruchomiono interaktywnie (PID={proc.pid}), job={job_id}"}
        else:
            # Tryb capture – zbieramy stdout/stderr i zapisujemy do jobs
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                preexec_fn=_preexec_resource_limits,
            )
            try:
                out, err = proc.communicate(timeout=PY_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                proc.kill()
                out, err = proc.communicate()
                return {"ok": False, "msg": f"[PY] Timeout po {PY_TIMEOUT_SEC}s", "stdout": out[:PY_STDOUT_MAX], "stderr": err[:PY_STDOUT_MAX]}

            with open(os.path.join(job_dir, "stdout.txt"), "w", encoding="utf-8", errors="replace") as f:
                f.write(out)
            with open(os.path.join(job_dir, "stderr.txt"), "w", encoding="utf-8", errors="replace") as f:
                f.write(err)

            ok = (proc.returncode == 0)
            msg = f"[PY] Exit={proc.returncode}, job={job_id}, cwd={cwd}"
            return {
                "ok": ok,
                "msg": msg,
                "stdout": out[:PY_STDOUT_MAX],
                "stderr": err[:PY_STDOUT_MAX],
                "job": job_id,
                "dir": job_dir,
                "cmd": " ".join(shlex.quote(x) for x in cmd),
            }
    except Exception as e:
        return {"ok": False, "msg": f"[PY] Błąd uruchomienia: {e.__class__.__name__}: {e}"}


def handle_console_line_py(line: str) -> str | None:
    s = line.strip()
    if not s.startswith("!py "):
        return None

    parts = shlex.split(s)
    if len(parts) < 2:
        return "[PY] Użycie: !py <skrypt.py> [args]"

    script = parts[1]
    args = parts[2:]

    if not os.path.isabs(script):
        found = None
        for base in PY_ALLOW_DIRS:
            cand = os.path.join(base, script)
            if os.path.exists(cand):
                found = cand
                break
        script = found or script

    res = run_python_script(script, args)
    out = res.get("stdout", "").rstrip()
    err = res.get("stderr", "").rstrip()
    msg = res.get("msg", "")
    reply = msg
    if out:
        reply += "\n[stdout]\n" + out
    if err:
        reply += "\n[stderr]\n" + err
    return reply

# =================== HELP ===================
