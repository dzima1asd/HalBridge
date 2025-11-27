#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Dict, List, Optional, Tuple

"""
HALbridge — modules/code.py
FAZY 1–4: sandbox, świadomość środowiska, rejestracja i inteligencja

• Sandbox: blokady importów/wywołań, izolowane uruchamianie z timeoutem.
• Środowisko: detekcja GUI/TTY/SSH itp.
• Rejestr: integracja z modules/code_registry.py (artefakty i ślady).
• Inteligencja: integracja z modules/intelligence.py (analiza promptu, walidacja).
• BUS: publikacja zdarzeń start/stop wykonania.
• CLI: --run-file, --run-stdin, --env
"""

import os, sys, re, time, json, uuid, platform, getpass, socket, subprocess, textwrap
from pathlib import Path

# --- Importy zależne (łagodne) ---
# --- Importy zależne (łagodne) ---
try:
    from modules.bus import BUS
except Exception:
    BUS = None

try:
    from modules import intelligence
except Exception:
    intelligence = None

try:
    from modules import auto_heal
except Exception:
    auto_heal = None

try:
    from modules import code_registry
except Exception:
    code_registry = None

try:
    from modules import integration
except Exception:
    integration = None

try:
    from modules import integration
except Exception:
    integration = None

# --- Ścieżki i katalogi ---
HOME = Path.home()
DATA_DIR = HOME / ".local/share/halbridge"
LOG_DIR = DATA_DIR / "logs"
TMP_DIR = DATA_DIR / "tmp"
CFG_PATH = HOME / ".config/halbridge/code_config.json"
LOG_FILE = LOG_DIR / "code_exec.log"

for d in (LOG_DIR, TMP_DIR, CFG_PATH.parent):
    d.mkdir(parents=True, exist_ok=True)

# --- Domyślna konfiguracja ---
DEFAULT_CFG = {
    "exec_timeout_sec": 8,
    "gen_timeout_sec": 20,
    "token_budget": 2000,
    "profile": "headless",
    "policy_overrides": {
        "headless": {
            "blocked_imports": ["matplotlib", "tkinter", "pygame", "requests", "socket"],
            "blocked_calls": ["os.system"],
        },
        "iot": {
            "blocked_imports": ["matplotlib", "tkinter", "pygame", "requests", "socket"],
            "blocked_calls": ["os.system"],
        },
        "analysis": {
            "blocked_imports": ["tkinter", "pygame", "socket"],
            "blocked_calls": ["os.system"],
        },
    },
}

# --- Logi pomocnicze ---
def _log_event(**rec):
    rec.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


# --- Konfiguracja ---
def _load_cfg() -> dict:
    if not CFG_PATH.exists():
        CFG_PATH.write_text(json.dumps(DEFAULT_CFG, indent=2, ensure_ascii=False), encoding="utf-8")
        return json.loads(json.dumps(DEFAULT_CFG))
    try:
        data = json.loads(CFG_PATH.read_text(encoding="utf-8"))
        merged = json.loads(json.dumps(DEFAULT_CFG))

        def deep_merge(dst, src):
            for k, v in src.items():
                if isinstance(v, dict) and isinstance(dst.get(k), dict):
                    deep_merge(dst[k], v)
                else:
                    dst[k] = v

        deep_merge(merged, data or {})
        return merged
    except Exception:
        return json.loads(json.dumps(DEFAULT_CFG))


# --- Detekcja środowiska ---
def detect_environment() -> dict:
    env = os.environ
    display = env.get("DISPLAY") or env.get("WAYLAND_DISPLAY")
    is_ssh = bool(env.get("SSH_CONNECTION") or env.get("SSH_CLIENT"))
    try:
        is_tty = sys.stdout.isatty()
    except Exception:
        is_tty = False
    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "python": platform.python_version(),
        "is_ssh": is_ssh,
        "display": display or "",
        "has_gui": bool(display),
        "is_tty": is_tty,
        "user": getpass.getuser(),
        "hostname": socket.gethostname(),
    }


def get_profile(env: dict, override: Optional[str], cfg: dict) -> str:
    return override or cfg.get("profile", "headless")


# --- Polityka bezpieczeństwa ---
class SecurityPolicy:
    def __init__(self, blocked_imports: List[str], blocked_calls: List[str]):
        self.blocked_imports = blocked_imports
        self.blocked_calls = blocked_calls


def _policy_for_profile(profile: str, cfg: dict) -> SecurityPolicy:
    p = cfg.get("policy_overrides", {}).get(profile, {})
    return SecurityPolicy(
        list(p.get("blocked_imports", [])),
        list(p.get("blocked_calls", [])),
    )


# --- Preflight: analiza kodu przed wykonaniem ---
def preflight_check(code_str: str, policy: SecurityPolicy) -> List[str]:
    out: List[str] = []
    lines = code_str.splitlines()
    for i, L in enumerate(lines, 1):
        for m in policy.blocked_imports:
            if re.search(rf"\b(import|from)\s+{re.escape(m)}\b", L):
                out.append(f"SandboxViolation: blocked import '{m}' (line {i})")
        for c in policy.blocked_calls:
            if re.search(rf"{re.escape(c)}\s*\(", L):
                out.append(f"SandboxViolation: blocked call '{c}' (line {i})")
    return out


# --- Minimalne środowisko podprocesu ---
def _minimal_env() -> Dict[str, str]:
    keep = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG") or k.startswith("LC_")}
    keep["PYTHONUNBUFFERED"] = "1"
    return keep


# --- Wrapper dla podprocesu (blokada importów i os.system) ---
def _wrapper_source(user_code_path: str, policy: SecurityPolicy) -> str:
    blocked = json.dumps(policy.blocked_imports)
    calls = json.dumps(policy.blocked_calls)
    return textwrap.dedent(f"""
        import sys, runpy, os, importlib.abc
        BLOCKED = set({blocked})
        CALLS = set({calls})
        class BlockedFinder(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                root = fullname.split('.', 1)[0]
                if root in BLOCKED:
                    raise ImportError(f"SandboxViolation: blocked import '{{root}}'")
                return None
        sys.meta_path.insert(0, BlockedFinder())
        if "os.system" in CALLS:
            def _blocked(*a, **k):
                raise RuntimeError("SandboxViolation: blocked call 'os.system'")
            os.system = _blocked
        try:
            runpy.run_path({user_code_path!r}, run_name="__main__")
        except ImportError as e:
            sys.stderr.write(str(e) + "\\n"); sys.exit(2)
        except Exception:
            import traceback; traceback.print_exc(); sys.exit(1)
    """).strip() + "\n"


# --- Wykonanie w podprocesie ---
def _execute_user_code(code_path: Path, policy: SecurityPolicy, timeout: int) -> Tuple[int, str, str, float]:
    wrap = _wrapper_source(str(code_path), policy)
    wp = TMP_DIR / f"wrap_{uuid.uuid4().hex}.py"
    wp.write_text(wrap, encoding="utf-8")
    t0 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(wp)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            env=_minimal_env(),
        )
        return p.returncode, p.stdout, p.stderr, time.time() - t0
    except subprocess.TimeoutExpired:
        return 124, "", f"Timeout after {timeout}s", time.time() - t0
    finally:
        wp.unlink(missing_ok=True)


# --- API: run_snippet / run_file ---
def run_snippet(
    # [auto] log: wejście do run_snippet
code_str: str, prompt: Optional[str] = None, profile: Optional[str] = None) -> dict:
    cfg = _load_cfg()
    env = detect_environment()

    # FAZA 2: analiza promptu
    meta = {}
    if intelligence and prompt:
        try:
            meta = intelligence.analyze_prompt(prompt)
            if BUS:
                BUS.publish("code.intent", meta)
            if integration:
                try:
                    integration.route(meta, {"code": code_str, "source": "snippet", "path": None})
                except Exception:
                    pass
            profile = meta.get("profile") or profile
        except Exception:
            meta = {}

    prof = get_profile(env, profile, cfg)
    policy = _policy_for_profile(prof, cfg)

    if BUS:
        BUS.publish("code.run.start", {"src": "snippet", "profile": prof})

    findings = preflight_check(code_str, policy)
    if findings:
        err = "\n".join(findings)
        _log_event(src="snippet", profile=prof, returncode=2, stderr_len=len(err), stdout_len=0, duration_ms=0)
        if BUS:
            BUS.publish("code.run.done", {"src": "snippet", "profile": prof, "rc": 2})
        return {"ok": False, "stdout": "", "stderr": err, "returncode": 2, "env": env, "profile": prof, "duration_ms": 0}

    code_path = TMP_DIR / f"user_{uuid.uuid4().hex}.py"
    code_path.write_text(code_str, encoding="utf-8")

    try:
        rc, out, err, dur = _execute_user_code(code_path, policy, int(cfg.get("exec_timeout_sec", 8)))
        result = {
            "ok": rc == 0,
            "stdout": out,
            "stderr": err,
            "returncode": rc,
            "env": env,
            "profile": prof,
            "duration_ms": int(dur * 1000),
        }

        _log_event(src="snippet", profile=prof, returncode=rc, stderr_len=len(err), stdout_len=len(out), duration_ms=int(dur * 1000))

        # FAZA 3: rejestr artefaktu
        if code_registry:
            try:
                meta_rec = {"env": env, "profile": prof, "ok": rc == 0}
                meta_rec.update(meta or {})
                code_registry.save_artifact(code_str, project=prof, filename=None, meta=meta_rec)
            except Exception:
                pass

        # FAZA 2: walidacja i sugestie
        if intelligence:
            try:
                result["valid"] = intelligence.validate_result(result)
                if not result["valid"] and err:
                    result["suggestion"] = intelligence.suggest_fix(err)
            except Exception:
                pass

        if BUS:
            BUS.publish("code.run.done", {"src": "snippet", "profile": prof, "rc": rc})

        # FAZA 6: logowanie błędów do auto_heal
        if auto_heal and (not rc == 0):
            try:
                auto_heal.record_failure("snippet", str(code_path), err, {"env": env, "profile": prof})
            except Exception:
                pass

        return result
    finally:
        try:
            code_path.unlink(missing_ok=True)
        except Exception:
            pass


def run_file(path: str, profile: Optional[str] = None) -> dict:
    cfg = _load_cfg()
    env = detect_environment()
    prof = get_profile(env, profile, cfg)
    policy = _policy_for_profile(prof, cfg)

    if BUS:
        BUS.publish("code.run.start", {"src": "file", "path": path, "profile": prof})

    p = Path(path).expanduser().resolve()
    if not p.exists():
        msg = f"File not found: {p}"
        _log_event(src="file", path=str(p), profile=prof, returncode=2, stderr_len=len(msg), stdout_len=0, duration_ms=0)
        if BUS:
            BUS.publish("code.run.done", {"src": "file", "profile": prof, "rc": 2})
        return {"ok": False, "stdout": "", "stderr": msg, "returncode": 2, "env": env, "profile": prof, "duration_ms": 0}

    txt = p.read_text(encoding="utf-8", errors="replace")
    findings = preflight_check(txt, policy)
    if findings:
        err = "\n".join(findings)
        _log_event(src="file", path=str(p), profile=prof, returncode=2, stderr_len=len(err), stdout_len=0, duration_ms=0)
        if BUS:
            BUS.publish("code.run.done", {"src": "file", "profile": prof, "rc": 2})
        return {"ok": False, "stdout": "", "stderr": err, "returncode": 2, "env": env, "profile": prof, "duration_ms": 0}

    rc, out, err, dur = _execute_user_code(p, policy, int(cfg.get("exec_timeout_sec", 8)))
    if "auto_heal" in globals() and auto_heal and rc != 0:
        auto_heal.record_failure("file", str(p), err, {"env": env, "profile": prof})
    result = {
        "ok": rc == 0,
        "stdout": out,
        "stderr": err,
        "returncode": rc,
        "env": env,
        "profile": prof,
        "duration_ms": int(dur * 1000),
    }

    _log_event(src="file", path=str(p), profile=prof, returncode=rc, stderr_len=len(err), stdout_len=len(out), duration_ms=int(dur * 1000))

    if code_registry:
        try:
            code_registry.register_path(str(p), project=prof, meta={"src": "sandbox", "ok": rc == 0})
        except Exception:
            pass

    if intelligence:
        try:
            result["valid"] = intelligence.validate_result(result)
            if not result["valid"] and err:
                result["suggestion"] = intelligence.suggest_fix(err)
        except Exception:
            pass

    if BUS:
        BUS.publish("code.run.done", {"src": "file", "profile": prof, "rc": rc})

        # FAZA 6: logowanie błędów do auto_heal
        if auto_heal and (not rc == 0):
            try:
                auto_heal.record_failure("snippet", str(code_path), err, {"env": env, "profile": prof})
            except Exception:
                pass

    return result


# --- CLI ---
def _cmd_run_file(args):
    res = run_file(args.path, profile=args.profile)
    if res.get("stdout"):
        sys.stdout.write(res["stdout"])
        if not res["stdout"].endswith("\n"):
            sys.stdout.write("\n")
    if res.get("stderr"):
        sys.stderr.write(res["stderr"])
        if not res["stderr"].endswith("\n"):
            sys.stderr.write("\n")
    sys.exit(0 if res.get("ok") else (res.get("returncode") or 1))


def _cmd_run_stdin(args):
    code = sys.stdin.read()
    res = run_snippet(code, prompt=args.prompt, profile=args.profile)
    if res.get("stdout"):
        sys.stdout.write(res["stdout"])
        if not res["stdout"].endswith("\n"):
            sys.stdout.write("\n")
    if res.get("stderr"):
        sys.stderr.write(res["stderr"])
        if not res["stderr"].endswith("\n"):
            sys.stderr.write("\n")
    sys.exit(0 if res.get("ok") else (res.get("returncode") or 1))


def _cmd_env(args):
    env = detect_environment()
    cfg = _load_cfg()
    prof = get_profile(env, args.profile, cfg)
    preamble = ""
    if intelligence:
        try:
            preamble = f"EnvironmentProfile={prof}; GUI={env.get('has_gui')}; Runtime={'gui' if env.get('has_gui') else 'terminal'}; Network=Restricted; IO=FilesystemLimited"
        except Exception:
            preamble = ""
    print(json.dumps({"env": env, "profile": prof, "preamble": preamble}, indent=2, ensure_ascii=False))


def main():
    import argparse
    ap = argparse.ArgumentParser(description="HALbridge Code Sandbox (Phases 1–4)")
    sub = ap.add_subparsers(dest="cmd")

    p1 = sub.add_parser("--run-file", help="Uruchom plik .py w sandboxie")
    p1.add_argument("path", help="Ścieżka do pliku .py")
    p1.add_argument("--profile", choices=["headless", "iot", "analysis"], default=None)
    p1.set_defaults(func=_cmd_run_file)

    p2 = sub.add_parser("--run-stdin", help="Czytaj kod ze stdin i uruchom w sandboxie")
    p2.add_argument("--profile", choices=["headless", "iot", "analysis"], default=None)
    p2.add_argument("--prompt", help="Opcjonalny prompt do analizy (FAZA 2)", default=None)
    p2.set_defaults(func=_cmd_run_stdin)

    p3 = sub.add_parser("--env", help="Pokaż detekcję środowiska i preambułę")
    p3.add_argument("--profile", choices=["headless", "iot", "analysis"], default=None)
    p3.set_defaults(func=_cmd_env)

    args = ap.parse_args()
    if not hasattr(args, "func"):
        ap.print_help()
        sys.exit(2)
    args.func(args)


if __name__ == "__main__":
    main()

# [auto] dodaj komentarz: próba inteligentnej łatki 2
