import os
import re
import shlex
import stat
import sys
import time
import json
import sqlite3
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Set, Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import argparse
import platform
import shutil
import importlib.util
import ast
import csv
import uuid
import resource
import pathlib

# --- Moduły agenta ---
from modules.hardware_bridge import HardwareBridge
from modules.browser_bridge import BrowserBridge
from modules.intents.recognizer import recognize_intent
from modules.intents.extract_slots import extract_slots
from modules.policy.router import route
from modules.guardrails import preflight
from modules.self_heal import try_self_heal
from modules.metrics import stat_intent_ok, stat_intent_fail, stat_slot_fill, stat_slot_missing
from modules.dialog.manager_v2 import ask_for_missing_slots
from modules.tools.registry import registry
from modules.tools.web_fetch import resolve_natural_query

# --- Instancje globalne ---
bridge = HardwareBridge()
browser = BrowserBridge()
def intent_pipeline(user_text):
    intent_info = recognize_intent(user_text)
    intent = intent_info.get("intent")

    if not intent:
        stat_intent_fail()
        return {"error": "unknown_intent"}

    stat_intent_ok()

    slots = extract_slots(user_text, intent)
    if slots:
        stat_slot_fill()
    else:
        stat_slot_missing()

    required = ["device"] if intent.startswith("iot.") else []
    ask = ask_for_missing_slots(required, slots)
    if ask:
        return {"ask": ask}

    plan = route(intent, slots)
    pf = preflight(plan)

    if not pf.get("ok"):
        healed = try_self_heal(intent, plan, pf)
        if healed.get("ok"):
            plan["slots"] = healed["slots"]
        else:
            return {"error": pf}

    return {"plan": plan}

# ---- task intelligence layer ----
try:
    from modules import intelligence
except Exception:
    intelligence = None

# ---- code registry integration ----
try:
    from modules import code_registry
except Exception:
    code_registry = None

# ---- optional sandbox bridge ----
try:
    from modules import code as code_sandbox  # modules/code.py (Phase 1)
except Exception:
    code_sandbox = None

# ---- task intelligence layer ----
try:
    from modules import intelligence
except Exception:
    intelligence = None

# --- [konfiguracja wykonania py] ---
PY_ALLOW_DIRS = [
    "/opt/halbridge",                  # główny katalog projektu
    "/opt/halbridge/scripts",          # Twoje skrypty
    os.path.expanduser("~/HALbridge"), # Twoja ścieżka dev
]
PYTHON_VENV = "/opt/halbridge/venv/bin/python3"  # jeśli masz venv; inaczej zostanie python3
PY_TIMEOUT_SEC = 60
PY_STDOUT_MAX = 200_000  # 200 kB max do konsoli
PY_RAM_LIMIT_MB = 256
PY_CPU_SECS = 30

JOBS_DIR = os.path.expanduser("~/.local/share/halbridge/jobs")
os.makedirs(JOBS_DIR, exist_ok=True)

# Moduły opcjonalne
try:
    import requests  # używane w SystemInspector.get_ip_address
except Exception:
    requests = None

try:
    import psutil    # używane w SystemInspector
except Exception:
    psutil = None

try:
    import getpass
except Exception:
    getpass = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

APP_VERSION = "v3.2"

# --- Globalny przełącznik trybu uruchamiania skryptów Python ---
GLOBAL_PY_EXEC_MODE = globals().get("GLOBAL_PY_EXEC_MODE", "interactive")  # "interactive" | "capture"

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

def show_help() -> str:
    return (
        "📚 Pomoc:\n"
        "  help                      — ten ekran\n"
        "  about                     — wersja i model\n"
        "  strict on|off             — włącz/wyłącz STRICT (NLP→bash dla wszystkiego)\n"
        "  model <nazwa>             — ustaw model (np. gpt-4o-mini)\n"
        "  temp <0.0-1.0>            — ustaw temperaturę LLM\n"
        "  max_tokens <int>          — limit tokenów odpowiedzi\n"
        "  tokens                    — skrót kosztów/zużycia\n"
        "  tokens report             — pełny raport (sumy i średnie)\n"
        "  tokens reset              — wyzeruj liczniki (JSON z sumami)\n"
        "  logs tail [N] / grep / export / clear — operacje na logach\n"
        "  project list|new|open|pwd — zarządzanie projektami\n"
        "  read / write              — sandbox plików\n"
        "  ai <prompt>               — rozmowa bez wykonywania\n"
        "  code [plik.py] <prompt>   — generuj→napraw→zapisz→uruchom\n"
        "  vcs init|status|log|diff|commit \"msg\" — git w projekcie\n"
        "  net on|off|allow|deny|list|get — sieć (whitelist)\n"
        "  !<komenda>                — surowy shell\n"
        "  exit                      — wyjście\n"
    )

# =================== CONFIG ===================

@dataclass
class Config:
    LOG_FILE: str = "command_log.json"  # legacy
    SAFETY_MODE: bool = True
    MAX_HISTORY: int = 200

    ENABLE_FILE_OPS: bool = True
    ENABLE_NETWORK_OPS: bool = False   # sieć OFF na start (włącz: 'net on')
    STRICT_MODE: bool = True

    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TEMPERATURE: float = 0.2
    OPENAI_MAX_TOKENS: int = 1200

    DB_PATH: str = "agent_memory.sqlite3"
    PROJECTS_DIR: str = "projects"
    CURRENT_PROJECT_FILE: str = "projects/.current"

    EXEC_TIMEOUT: int = 60

    # Sandbox plików
    ALLOWED_DIRS: List[str] = None
    BLACKLISTED_DIRS: List[str] = None

    # ---------- Token meter ----------
    TOKEN_LOG_PATH: str = "token_usage.csv"        # historia wywołań
    TOKEN_TOTALS_PATH: str = "token_totals.json"   # sumy kumulowane

    # ---------- Proste logi OUT/ERR ----------
    RUN_OUT_FILE: str = "halbridge.out"
    RUN_ERR_FILE: str = "halbridge.err"

    USD_TO_PLN: float = 3.64                       # stały kurs
    MODEL_PRICING: dict = None

    # ---------- Logger ----------
    LOG_DIR: str = "logs"
    APP_LOG_FILE: str = "logs/agent.log"
    LOG_MAX_BYTES: int = 1_000_000                 # 1 MB
    LOG_BACKUPS: int = 5
    LOG_TS_FMT: str = "%Y-%m-%dT%H:%M:%S.%fZ"

    # ---------- Network tool ----------
    NET_ALLOWED: set = field(default_factory=set)  # dozwolone domeny
    NET_TIMEOUT: int = 6                           # sekundy
    NET_MAX_BYTES: int = 1_000_000                 # 1 MB limit odpowiedzi

    # ---------- Memory / Summaries ----------
    SUMMARY_MSG_THRESHOLD: int = 20                # co ile wiadomości robić streszczenie
    SUMMARY_WINDOW: int = 30                       # ile ostatnich msg do streszczenia
    SUMMARY_MAX_CHARS: int = 2000                  # budżet znaków na streszczenie

    def __post_init__(self):
        if self.MODEL_PRICING is None:
            self.MODEL_PRICING = {
                "gpt-4o-mini": {"input_per_1k": 0.005, "output_per_1k": 0.015},
            }
        if self.ALLOWED_DIRS is None:
            self.ALLOWED_DIRS = [str(Path(self.PROJECTS_DIR).resolve())]
        if self.BLACKLISTED_DIRS is None:
            self.BLACKLISTED_DIRS = ["/etc", "/bin", "/sbin", "/usr", "/boot", "/dev", "/proc", "/sys"]

# =================== UTILS / ENV ===================

def ensure_dirs(cfg: Config):
    Path(cfg.PROJECTS_DIR).mkdir(parents=True, exist_ok=True)
    Path(cfg.LOG_DIR).mkdir(parents=True, exist_ok=True)
    cur = Path(cfg.CURRENT_PROJECT_FILE)
    if not cur.exists():
        (Path(cfg.PROJECTS_DIR) / "default").mkdir(parents=True, exist_ok=True)
        cur.write_text("default", encoding="utf-8")


class MemoryStore:
    """
    Tabele:
      sessions(id TEXT PK, created_at TEXT)
      messages(id INTEGER PK, session_id TEXT, role TEXT, content TEXT, created_at TEXT)
      summaries(id INTEGER PK, session_id TEXT, upto_msg_id INTEGER, content TEXT, created_at TEXT)
      memories(id INTEGER PK, session_id TEXT, kind TEXT, content TEXT, is_pinned INTEGER, created_at TEXT)
    """
    def __init__(self, cfg: Config):
        self.db = sqlite3.connect(cfg.DB_PATH)
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at TEXT
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                role TEXT,
                content TEXT,
                created_at TEXT
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                upto_msg_id INTEGER,
                content TEXT,
                created_at TEXT
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                kind TEXT,
                content TEXT,
                is_pinned INTEGER DEFAULT 0,
                created_at TEXT
            )
            """
        )
        self.db.commit()

    def ensure_session(self, session_id: str):
        cur = self.db.execute("SELECT id FROM sessions WHERE id=?", (session_id,))
        if not cur.fetchone():
            self.db.execute(
                "INSERT INTO sessions (id, created_at) VALUES (?, ?)",
                (session_id, datetime.now(tz=tz.utc).isoformat()),
            )
            self.db.commit()

    def add_message(self, session_id: str, role: str, content: str) -> int:
        cur = self.db.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, datetime.now(tz=tz.utc).isoformat()),
        )
        self.db.commit()
        return cur.lastrowid

    def get_recent_messages(self, session_id: str, limit: int = 12) -> List[Dict]:
        cur = self.db.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows = cur.fetchall()
        rows.reverse()
        return [{"role": r, "content": c} for (r, c) in rows]

    def get_messages_since(self, session_id: str, after_id: int, limit: int = 100) -> List[Dict]:
        cur = self.db.execute(
            "SELECT id, role, content FROM messages WHERE session_id=? AND id>? ORDER BY id ASC LIMIT ?",
            (session_id, after_id, limit),
        )
        return [{"id": i, "role": r, "content": c} for (i, r, c) in cur.fetchall()]

    def last_message_id(self, session_id: str) -> int:
        cur = self.db.execute(
            "SELECT COALESCE(MAX(id), 0) FROM messages WHERE session_id=?",
            (session_id,),
        )
        return int(cur.fetchone()[0] or 0)

    def last_summary(self, session_id: str) -> Tuple[int, str]:
        cur = self.db.execute(
            "SELECT upto_msg_id, content FROM summaries WHERE session_id=? ORDER BY id DESC LIMIT 1",
            (session_id,),
        )
        row = cur.fetchone()
        if not row:
            return 0, ""
        return int(row[0] or 0), row[1] or ""

    def add_summary(self, session_id: str, upto_msg_id: int, content: str):
        self.db.execute(
            "INSERT INTO summaries (session_id, upto_msg_id, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, upto_msg_id, content, datetime.now(tz=tz.utc).isoformat()),
        )
        self.db.commit()

    def count_since_summary(self, session_id: str) -> int:
        last_id, _ = self.last_summary(session_id)
        cur = self.db.execute(
            "SELECT COUNT(*) FROM messages WHERE session_id=? AND id>?",
            (session_id, last_id),
        )
        return int(cur.fetchone()[0] or 0)

    # ---- Memories (pinned facts / notes) ----

    def add_memory(self, session_id: str, content: str, kind: str = "note", pinned: bool = False) -> int:
        cur = self.db.execute(
            "INSERT INTO memories (session_id, kind, content, is_pinned, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, kind, content, 1 if pinned else 0, datetime.now(tz=tz.utc).isoformat()),
        )
        self.db.commit()
        return cur.lastrowid

    def list_memories(self, session_id: str, limit: int = 50) -> List[Dict]:
        cur = self.db.execute(
            "SELECT id, kind, content, is_pinned, created_at FROM memories WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        )
        rows = []
        for i, k, c, p, ts_ in cur.fetchall():
            rows.append({"id": i, "kind": k, "content": c, "pinned": bool(p), "created_at": ts_})
        return rows

    def pinned_memories(self, session_id: str) -> List[str]:
        cur = self.db.execute(
            "SELECT content FROM memories WHERE session_id=? AND is_pinned=1 ORDER BY id ASC",
            (session_id,),
        )
        return [r[0] for r in cur.fetchall()]

    def pin_memory(self, mem_id: int, pin: bool = True) -> bool:
        self.db.execute("UPDATE memories SET is_pinned=? WHERE id=?", (1 if pin else 0, mem_id))
        self.db.commit()
        return True

    def clear_memories(self, session_id: str) -> int:
        cur = self.db.execute("DELETE FROM memories WHERE session_id=?", (session_id,))
        self.db.commit()
        return cur.rowcount

    def search_memories(self, session_id: str, query: str, limit: int = 10) -> List[Dict]:
        # proste LIKE po słowach
        terms = [t for t in re.split(r"\s+", query.strip()) if t]
        if not terms:
            return []
        sql = "SELECT id, kind, content, is_pinned, created_at FROM memories WHERE session_id=?"
        params = [session_id]
        for t in terms:
            sql += " AND content LIKE ?"
            params.append(f"%{t}%")
        sql += " ORDER BY is_pinned DESC, id DESC LIMIT ?"
        params.append(limit)
        cur = self.db.execute(sql, tuple(params))
        rows = []
        for i, k, c, p, ts_ in cur.fetchall():
            rows.append({"id": i, "kind": k, "content": c, "pinned": bool(p), "created_at": ts_})
        return rows

# =================== LOGGER Z ROTACJĄ ===================

class RotatingLogger:
    def __init__(self, cfg: Config):
        self.path = Path(cfg.APP_LOG_FILE)
        self.max_bytes = cfg.LOG_MAX_BYTES
        self.backups = cfg.LOG_BACKUPS
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event: str, **kwargs):
        rec = {
            "ts": datetime.now(tz=tz.utc).isoformat(timespec="seconds"),
            "event": event,
            **kwargs,
        }
        line = json.dumps(rec, ensure_ascii=False)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        self._rotate()

    def _rotate(self):
        if self.path.exists() and self.path.stat().st_size > self.max_bytes:
            # przesuwamy .N -> .N+1
            for i in range(self.backups, 0, -1):
                src = self.path.with_suffix(self.path.suffix + f".{i}")
                dst = self.path.with_suffix(self.path.suffix + f".{i+1}")
                if src.exists():
                    if i == self.backups:
                        src.unlink(missing_ok=True)
                    else:
                        src.rename(dst)
            self.path.rename(self.path.with_suffix(self.path.suffix + ".1"))

    def tail(self, n: int = 100) -> str:
        if not self.path.exists():
            return "(brak logów)"
        with open(self.path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return "".join(lines[-n:])

    def show(self, pattern: Optional[str] = None) -> List[dict]:
        if not self.path.exists():
            return []
        rows = []
        rx = re.compile(pattern, re.IGNORECASE) if pattern else None
        with open(self.path, "r", encoding="utf-8") as f:
            for L in f:
                L = L.strip()
                if not L:
                    continue
                try:
                    rec = json.loads(L)
                except Exception:
                    continue
                if rx is None or rx.search(json.dumps(rec, ensure_ascii=False)):
                    rows.append(rec)
        return rows

    def export(self, out_path: str) -> str:
        if not self.path.exists():
            return "❌ Brak logów do eksportu"
        try:
            outp = Path(out_path)
            outp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.path, outp)
            return f"✅ Wyeksportowano do {out_path}"
        except Exception as e:
            return f"❌ Błąd eksportu: {e}"

    def clear(self) -> str:
        try:
            self.path.unlink(missing_ok=True)
            base = str(self.path)
            for i in range(1, self.backups + 1):
                Path(f"{base}.{i}").unlink(missing_ok=True)
            return "🧹 Logi wyczyszczone"
        except Exception as e:
            return f"❌ Błąd czyszczenia: {e}"

# =================== SYSTEM INSPECTOR ===================

class SystemInspector:
    @staticmethod
    def get_system_info() -> dict:
        try:
            mem = psutil.virtual_memory() if psutil else None
            disk = psutil.disk_usage('/') if psutil else None
            return {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_cores": os.cpu_count(),
                "memory": (
                    {"total": mem.total, "available": mem.available, "percent": mem.percent}
                    if mem else None
                ),
                "disk_usage": (
                    {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent}
                    if disk else None
                ),
                "current_user": (getpass.getuser() if getpass else None),
                "hostname": platform.node(),
                "ip_address": SystemInspector.get_ip_address(),
                "python_version": platform.python_version(),
                "timestamp": datetime.now(tz=tz.utc).isoformat(),
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_ip_address() -> str:
        try:
            if requests:
                return requests.get('https://api.ipify.org', timeout=3).text
        except Exception:
            pass
        try:
            if requests:
                return requests.get('https://ifconfig.me', timeout=3).text
        except Exception:
            pass
        return "127.0.0.1"

def render_diag(cfg: Config, api: "GPTChatAPI") -> str:
    """
    Zwraca zwięzły tekst diagnostyczny: ustawienia agenta, projekt,
    statystyki tokenów, pamięć, skrót danych systemowych i ogon logów.
    """
    lines: List[str] = []

    # Nagłówek / ustawienia
    lines.append("=== DIAGNOSTYKA AGENA ===")
    lines.append(f"Agent: {APP_VERSION}")
    lines.append(
        f"Model: {cfg.OPENAI_MODEL} | T={cfg.OPENAI_TEMPERATURE} | "
        f"MAXTOK={cfg.OPENAI_MAX_TOKENS}"
    )
    lines.append(
        f"STRICT: {'ON' if cfg.STRICT_MODE else 'OFF'} | "
        f"NET: {'ON' if cfg.ENABLE_NETWORK_OPS else 'OFF'} | "
        f"NET_ALLOWED: {len(cfg.NET_ALLOWED)} domen"
    )

    # Projekt
    try:
        proj_name = api.projects.current_name()
        proj_path = api.projects.current_path()
    except Exception:
        proj_name, proj_path = "(?)", "(?)"
    lines.append(f"Projekt: {proj_name} @ {proj_path}")

    # Pamięć (memories)
    try:
        total_mems = len(api.memory.list_memories(api.session_id, limit=1000))
        pinned_mems = len(api.memory.pinned_memories(api.session_id))
    except Exception:
        total_mems = pinned_mems = 0
    lines.append(f"Pamięci: {total_mems} (📌 {pinned_mems} pinned)")

    # Tokeny / koszt
    try:
        totals = api.meter._load_totals()
        pt = int(totals.get("prompt_tokens", 0))
        ct = int(totals.get("completion_tokens", 0))
        usd = float(totals.get("cost_usd", 0.0))
        pln = float(totals.get("cost_pln", 0.0))
        lines.append(
            f"Tokeny: prompt={pt}, completion={ct} | "
            f"Koszt: {usd:.4f} USD ~ {pln:.2f} PLN"
        )
    except Exception:
        lines.append("Tokeny: (brak danych)")

    # System (skrócona sekcja)
    try:
        si = SystemInspector.get_system_info()
        sys_part = []
        for k in ("system", "release", "machine", "python_version", "hostname", "ip_address"):
            if k in si and si[k] is not None:
                sys_part.append(f"{k}={si[k]}")
        lines.append("System: " + ", ".join(sys_part) if sys_part else "System: (n/d)")
    except Exception as e:
        lines.append(f"System: błąd: {e}")

    # Ostatnie wpisy logów
    try:
        tail_txt = api.logger.tail(12).rstrip()
        lines.append("--- Ostatnie logi ---")
        lines.append(tail_txt if tail_txt else "(brak logów)")
    except Exception:
        lines.append("--- Ostatnie logi ---")
        lines.append("(błąd odczytu)")

    return "\n".join(lines)

# =================== DIAGNOSTICS ===================

def render_diag(cfg: Config, api) -> str:
    try:
        sysinfo = SystemInspector.get_system_info()
    except Exception as e:
        sysinfo = {"error": str(e)}

    # tokeny (z pliku totals) + skrót ze `summary()`
    try:
        totals = api.meter._load_totals()  # wewnętrzne, ale przydatne do zbiorczego widoku
    except Exception:
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "cost_pln": 0.0}

    log_path = Path(cfg.APP_LOG_FILE)
    log_exists = log_path.exists()
    log_size = (log_path.stat().st_size if log_exists else 0)

    lines = []
    lines.append("=== DIAG ===")
    lines.append(f"time_utc: {datetime.now(tz=tz.utc).isoformat()}")
    lines.append(f"app_version: {APP_VERSION}")
    lines.append(f"model: {cfg.OPENAI_MODEL}  T={cfg.OPENAI_TEMPERATURE}  MAXTOK={cfg.OPENAI_MAX_TOKENS}")
    lines.append(f"strict_mode: {cfg.STRICT_MODE}  safety_mode: {cfg.SAFETY_MODE}")
    lines.append(f"network: {'ON' if cfg.ENABLE_NETWORK_OPS else 'OFF'}  timeout={cfg.NET_TIMEOUT}s  max={cfg.NET_MAX_BYTES}B")
    lines.append("net_whitelist: " + (", ".join(sorted(cfg.NET_ALLOWED)) if cfg.NET_ALLOWED else "(pusto)"))
    lines.append(f"project: {api.projects.current_name()}  @  {api.projects.current_path()}")
    lines.append("tokens: " + api.meter.summary())
    lines.append(f"tokens_totals: prompt={totals.get('prompt_tokens',0)}, completion={totals.get('completion_tokens',0)}, "
                 f"cost_usd={float(totals.get('cost_usd',0.0)):.4f}, cost_pln={float(totals.get('cost_pln',0.0)):.2f}")
    lines.append(f"log_file: {cfg.APP_LOG_FILE}  exists={log_exists}  size={log_size}B  backups={cfg.LOG_BACKUPS}")

    # Wybrane pola z sysinfo (żeby nie zalać ekranu)
    si_parts = []
    for k in ("system","release","machine","processor","cpu_cores","hostname","python_version","ip_address"):
        if k in sysinfo and sysinfo[k] is not None:
            si_parts.append(f"{k}={sysinfo[k]}")
    lines.append("system_info: " + (", ".join(si_parts) if si_parts else "(brak)"))

    return "\n".join(lines)

# =================== TOKEN METER ===================

class TokenMeter:
    def __init__(self, cfg: Config, logger: RotatingLogger):
        self.cfg = cfg
        self.logger = logger
        self.path = Path(cfg.TOKEN_TOTALS_PATH)

    def _load_totals(self) -> Dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save_totals(self, totals: Dict[str, Any]) -> None:
        self.path.write_text(json.dumps(totals, indent=2, ensure_ascii=False), encoding="utf-8")

    def add_usage(self, model: str, prompt_tokens: int, completion_tokens: int, note: str = "") -> None:
        totals = self._load_totals()
        pt = int(totals.get("prompt_tokens", 0)) + prompt_tokens
        ct = int(totals.get("completion_tokens", 0)) + completion_tokens
        usd_in = self.cfg.MODEL_PRICING.get(model, {}).get("input_per_1k", 0.0)
        usd_out = self.cfg.MODEL_PRICING.get(model, {}).get("output_per_1k", 0.0)
        cost_usd = float(totals.get("cost_usd", 0.0)) + (prompt_tokens / 1000) * usd_in + (completion_tokens / 1000) * usd_out
        cost_pln = cost_usd * self.cfg.USD_TO_PLN
        calls = int(totals.get("calls", 0)) + 1
        totals.update(
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=cost_usd,
            cost_pln=cost_pln,
            calls=calls,
        )
        self._save_totals(totals)
        self.logger.log("tokens.update",
                        model=model,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        cost_usd=cost_usd,
                        cost_pln=cost_pln,
                        note=note)

    def summary(self) -> str:
        t = self._load_totals()
        pt = int(t.get("prompt_tokens", 0))
        ct = int(t.get("completion_tokens", 0))
        usd = float(t.get("cost_usd", 0.0))
        pln = float(t.get("cost_pln", 0.0))
        calls = int(t.get("calls", 0))
        total_tokens = pt + ct
        avg_tokens = (total_tokens / calls) if calls else 0.0
        return f"🔢 Tokeny: prompt={pt}, completion={ct} | 💵 Koszt: {usd:.4f} USD ~ {pln:.2f} PLN | 📞 Wywołań: {calls}, Średnio/tokeny: {avg_tokens:.1f}"

    def reset(self):
        """Wyzeruj liczniki zużycia (sumy w JSON)."""
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "cost_pln": 0.0,
            "calls": 0
        }
        self._save_totals(totals)
        self.logger.log("tokens.reset")

    def report(self) -> str:
        """Szczegółowy raport użycia tokenów."""
        t = self._load_totals()
        pt = int(t.get("prompt_tokens", 0))
        ct = int(t.get("completion_tokens", 0))
        usd = float(t.get("cost_usd", 0.0))
        pln = float(t.get("cost_pln", 0.0))
        calls = int(t.get("calls", 0))
        total_tokens = pt + ct
        avg_tokens = (total_tokens / calls) if calls else 0.0
        return (
            f"=== RAPORT TOKENÓW ===\n"
            f"Prompt: {pt}\n"
            f"Completion: {ct}\n"
            f"Suma: {total_tokens}\n"
            f"Wywołań: {calls}\n"
            f"Średnio/tokeny na wywołanie: {avg_tokens:.1f}\n"
            f"Koszt: {usd:.4f} USD ~ {pln:.2f} PLN\n"
        )

# =================== PROJECTS + SANDBOX ===================

class ProjectManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        ensure_dirs(cfg)

    def _cur_file(self) -> Path:
        return Path(self.cfg.CURRENT_PROJECT_FILE)

    def current_name(self) -> str:
        try:
            return self._cur_file().read_text(encoding="utf-8").strip() or "default"
        except Exception:
            return "default"

    def current_path(self) -> Path:
        return Path(self.cfg.PROJECTS_DIR) / self.current_name()

    def list(self) -> List[str]:
        return sorted([p.name for p in Path(self.cfg.PROJECTS_DIR).iterdir() if p.is_dir()])

    def new(self, name: str) -> str:
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_") or "proj"
        path = Path(self.cfg.PROJECTS_DIR) / safe
        path.mkdir(parents=True, exist_ok=True)
        self._cur_file().write_text(safe, encoding="utf-8")
        return safe

    def open(self, name: str) -> bool:
        safe = re.sub(r"[^A-Za-z0-9_\-]", "_", name).strip("_")
        path = Path(self.cfg.PROJECTS_DIR) / safe
        if not path.is_dir():
            return False
        self._cur_file().write_text(safe, encoding="utf-8")
        return True

class GitManager:
    def __init__(self, cfg: Config, projects: ProjectManager, logger: RotatingLogger):
        self.cfg = cfg
        self.projects = projects
        self.logger = logger

    def _run(self, args: List[str], cwd: Optional[Path] = None) -> Tuple[bool, str]:
        try:
            p = subprocess.run(
                ["git"] + args,
                cwd=str(cwd or self.projects.current_path()),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=20,
                check=False,
            )
            out = p.stdout if p.returncode == 0 else (p.stderr or p.stdout)
            return p.returncode == 0, out
        except Exception as e:
            return False, str(e)

    def ensure_config(self, cwd: Path):
        # Ustaw bazową tożsamość jeśli nie ustawiona
        self._run(["config", "user.name"], cwd)
        ok, out = self._run(["config", "user.email"], cwd)
        if not ok or not out.strip():
            self._run(["config", "user.name", "agent"], cwd)
            self._run(["config", "user.email", "agent@example.invalid"], cwd)

    def init(self) -> str:
        cwd = self.projects.current_path()
        ok, out = self._run(["rev-parse", "--is-inside-work-tree"], cwd)
        if ok and out.strip() == "true":
            return "ℹ️ Repozytorium już istnieje."
        ok, out = self._run(["init"], cwd)
        if not ok:
            return f"❌ git init: {out}"
        self.ensure_config(cwd)
        self._run(["add", "-A"], cwd)
        self._run(["commit", "-m", "init"], cwd)
        return "✅ Repozytorium zainicjalizowane."

    def status(self) -> str:
        ok, out = self._run(["status", "--short"], self.projects.current_path())
        return out if ok else f"❌ git status: {out}"

    def log(self, n: int = 20) -> str:
        ok, out = self._run(["log", f"-{n}", "--oneline"], self.projects.current_path())
        return out if ok else f"❌ git log: {out}"

    def diff(self, path: Optional[str] = None) -> str:
        args = ["diff"]
        if path:
            args.append(path)
        ok, out = self._run(args, self.projects.current_path())
        return out if ok else f"❌ git diff: {out}"

    def commit(self, msg: str) -> str:
        cwd = self.projects.current_path()
        self._run(["add", "-A"], cwd)
        ok, out = self._run(["commit", "-m", msg], cwd)
        return out if ok else f"❌ git commit: {out}"

    def autocommit(self, msg: str) -> None:
        cwd = self.projects.current_path()
        self._run(["add", "-A"], cwd)
        ok, _ = self._run(["diff", "--cached", "--quiet"], cwd)
        # --quiet zwraca 1 gdy są zmiany; w naszym _run() ok==False => są zmiany
        if not ok:
            self._run(["commit", "-m", msg], cwd)

class FileOps:
    def __init__(self, cfg: Config, projects: ProjectManager):
        self.cfg = cfg
        self.projects = projects

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self.projects.current_path() / p
        return p.resolve()

    def _is_safe(self, abs_path: Path) -> bool:
        ap = str(abs_path)
        for bad in self.cfg.BLACKLISTED_DIRS:
            if ap.startswith(str(Path(bad).resolve())):
                return False
        for ok in self.cfg.ALLOWED_DIRS:
            if ap.startswith(str(Path(ok).resolve())):
                return True
        return False

    def write(self, path: str, content: str) -> bool:
        if not self.cfg.ENABLE_FILE_OPS:
            return False
        try:
            rp = self._resolve(path)
            if not self._is_safe(rp):
                return False
            rp.parent.mkdir(parents=True, exist_ok=True)
            rp.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def read(self, path: str) -> Optional[str]:
        try:
            rp = self._resolve(path)
            if not self._is_safe(rp):
                return None
            return rp.read_text(encoding="utf-8")
        except Exception:
            return None

# =================== COMMAND VALIDATION / EXECUTOR ===================

class CommandValidator:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.dangerous_keywords = [
            " shutdown", " poweroff", " reboot", " halt", " init 0",
            " mkfs", " :(){", " dd if=", "wget ", "curl ",
        ]
        self.dangerous_regex = [
            (r'rm\s+-rf\s+/', "Rekursywne usuwanie roota"),
            (r'(?:^| )systemctl\s+(?:stop|disable)\s+', "Zatrzymywanie usług"),
            (r'(?:^| )(ifconfig|ip)\s+\w+\s+down', "Wyłączanie interfejsu sieci"),
            (r'iptables\s+-F', "Czyszczenie firewall"),
        ]
        self.warning_regex = [
            (r'(?:^| )rm\s+', "Usuwanie plików"),
            (r'(?:^| )(apt|dnf|yum|pacman)\s+(install|remove|purge|-S|-R)', "Zarządzanie pakietami"),
            (r'(?:^| )(chmod|chown)\s+', "Zmiana uprawnień/właściciela"),
        ]

    def validate(self, cmd: str) -> Tuple[bool, Optional[str]]:
        if not self.cfg.SAFETY_MODE:
            return True, None
        low = f" {cmd.strip().lower()} "
        for kw in self.dangerous_keywords:
            if kw in low:
                return False, f"❌ Blokada bezpieczeństwa: {kw.strip()}"
        for pat, desc in self.dangerous_regex:
            if re.search(pat, low):
                return False, f"❌ Niebezpieczna operacja: {desc}"
        for pat, desc in self.warning_regex:
            if re.search(pat, low):
                return True, f"⚠️ Uwaga: {desc}"
        return True, None


class CommandExecutor:
    def __init__(self, cfg: Config, logger: "RotatingLogger"):
        self.cfg = cfg
        self.logger = logger

    def run(self, cmd: str, warn: Optional[str] = None) -> Tuple[bool, str]:
        """
        Uruchamia komendę w shellu z timeoutem i logowaniem.
        - Jeśli `warn` podane, zapisuje ostrzeżenie do RUN_ERR_FILE.
        - Stdout sukcesów dopisuje do RUN_OUT_FILE, błędy do RUN_ERR_FILE.
        Zwraca (success, output).
        """
        # Smart ping: domyślnie -c 4
        norm = cmd.strip()
        if norm.startswith("ping ") and " -c " not in norm:
            norm = norm + " -c 4"
            cmd = norm

        ts = datetime.now(tz=tz.utc).isoformat(timespec="seconds")

        # Opcjonalne ostrzeżenie od walidatora
        if warn:
            try:
                with open(self.cfg.RUN_ERR_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] WARN: {warn} for: {cmd}\n")
            except Exception:
                pass

        self.logger.log("exec.run", cmd=cmd)
        try:
            p = subprocess.run(
                cmd,
                shell=True,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.cfg.EXEC_TIMEOUT,
            )

            stdout = p.stdout or ""
            stderr = p.stderr or ""
            out = stdout if p.returncode == 0 else (stderr or stdout)

            # Log do plików OUT/ERR
            try:
                if p.returncode == 0:
                    if stdout:
                        with open(self.cfg.RUN_OUT_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{ts}] CMD: {cmd}\n{stdout}\n---\n")
                    if stderr:
                        with open(self.cfg.RUN_ERR_FILE, "a", encoding="utf-8") as f:
                            f.write(f"[{ts}] STDERR (rc=0) CMD: {cmd}\n{stderr}\n---\n")
                else:
                    with open(self.cfg.RUN_ERR_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{ts}] ERROR rc={p.returncode} CMD: {cmd}\n{out}\n---\n")
            except Exception:
                # Ciche — nie blokujemy wykonania, jeśli log się nie powiedzie
                pass

            self.logger.log("exec.done", cmd=cmd, rc=p.returncode, bytes=len((out or "").encode("utf-8")))
            if p.returncode == 0:
                return True, stdout
            return False, out

        except subprocess.TimeoutExpired:
            try:
                with open(self.cfg.RUN_ERR_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] TIMEOUT after {self.cfg.EXEC_TIMEOUT}s CMD: {cmd}\n---\n")
            except Exception:
                pass
            self.logger.log("exec.timeout", cmd=cmd)
            return False, "⏰ Przekroczono limit czasu wykonania"

        except Exception as e:
            try:
                with open(self.cfg.RUN_ERR_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] EXCEPTION CMD: {cmd}\n{str(e)}\n---\n")
            except Exception:
                pass
            self.logger.log("exec.error", cmd=cmd, error=str(e))
            return False, str(e)

# =================== LLM HELPERS (code preflight / sanitize) ===================

def extract_imports(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return sorted(mods)


def missing_third_party(code: str) -> List[str]:
    mods = extract_imports(code)
    std = getattr(sys, "stdlib_module_names", None)
    missing = []
    for m in mods:
        if std is not None and m in std:
            continue
        if std is None and m in {
            "sys","os","time","re","json","random","datetime","pathlib","subprocess",
            "select","socket","termios","tty","signal","shutil","tempfile","logging",
            "itertools","functools","collections","argparse","typing","enum","dataclasses",
            "hashlib","importlib","urllib","ast","traceback",
        }:
            continue
        if importlib.util.find_spec(m) is None:
            missing.append(m)
    return missing


def compile_check(code: str) -> Optional[str]:
    try:
        compile(code, "<generated>", "exec")
        return None
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno}, col {e.offset})"


def sanitize_llm_code(raw: str) -> str:
    m_py = re.search(r"```(?:python|py)\s*([\s\S]*?)```", raw, re.IGNORECASE)
    m_any = re.search(r"```+\s*([\s\S]*?)```+", raw) if not m_py else None
    code = (m_py.group(1) if m_py else (m_any.group(1) if m_any else raw)).strip()
    cleaned = []
    for line in code.splitlines():
        ls = line.strip()
        if not ls:
            cleaned.append(line); continue
        if ls.upper().startswith("WYKONAJ"):
            continue
        if ls.startswith("[") and ls.endswith("]"):
            continue
        if ls.startswith("/bin/sh:"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def repair_prompt(original_code: str, error_text: str, missing_mods: List[str]) -> str:
    advice = []
    if missing_mods:
        advice.append(
            "Usuń wszystkie zależności spoza standardowej biblioteki Pythona: "
            + ", ".join(missing_mods) + "."
        )
    if error_text:
        advice.append(f"Popraw błąd: {error_text}")
    advice.append("Zwróć WYŁĄCZNIE gotowy kod w Pythonie w bloku ```python``` bez komentarzy.")
    return (
        "Napraw poniższy program w Pythonie.\n\n"
        "Kod do poprawy:\n\n"
        "```python\n" + original_code + "\n```\n\n" + "\n".join(advice)
    )

PROMPT_RULES_FILE = os.path.expanduser("~/HALbridge/prompt_rules.txt")


def load_persistent_prompt_rules() -> list[str]:
    try:
        if not os.path.exists(PROMPT_RULES_FILE):
            return []
        rules: list[str] = []
        with open(PROMPT_RULES_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    continue
                rules.append(line)
        return rules
    except Exception:
        return []


# =================== NETWORK TOOL (SAFE HTTP GET) ===================

class HttpTool:
    def __init__(self, cfg: Config, logger: RotatingLogger):
        self.cfg = cfg
        self.logger = logger

    def _allowed_domain(self, url: str) -> Tuple[bool, str]:
        try:
            p = urlparse(url)
            host = (p.hostname or "").lower()
            if not host:
                return False, "❌ Nieprawidłowy URL"
            allowed_any = any(host == dom or host.endswith("." + dom) for dom in self.cfg.NET_ALLOWED)
            return (self.cfg.ENABLE_NETWORK_OPS and allowed_any), host
        except Exception:
            return False, "❌ Nieprawidłowy URL"

    def get(self, url: str, want_headers: bool = False) -> str:
        ok, info = self._allowed_domain(url)
        if not ok:
            if not self.cfg.ENABLE_NETWORK_OPS:
                return "🌐 Sieć jest wyłączona (użyj: net on)."
            return f"❌ Domena niedozwolona: {info}"

        self.logger.log("http.get", url=url)
        req = Request(url, headers={"User-Agent": "Agent/1.0"})
        try:
            with urlopen(req, timeout=self.cfg.NET_TIMEOUT) as resp:
                data = b""
                chunk = 64 * 1024
                total = 0
                while True:
                    part = resp.read(chunk)
                    if not part:
                        break
                    data += part
                    total += len(part)
                    if total > self.cfg.NET_MAX_BYTES:
                        return f"❌ Przekroczono limit odpowiedzi {self.cfg.NET_MAX_BYTES} B"
                try:
                    enc = resp.headers.get_content_charset() or "utf-8"
                except Exception:
                    enc = "utf-8"
                text = data.decode(enc, errors="replace")

                if want_headers:
                    hdrs = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
                    return f"[HEADERS]\n{hdrs}\n\n[BODY]\n{text}"
                return text
        except Exception as e:
            return f"❌ Błąd HTTP: {e}"

class ModuleRunner:
    """Bezpieczne uruchamianie modułów w katalogu modules/"""

    def __init__(self, cfg: Config, logger: RotatingLogger):
        self.cfg = cfg
        self.logger = logger
        self.base = Path("modules").resolve()

    def run(self, name: str, args: List[str] = None) -> str:
        if not re.match(r"^[A-Za-z0-9_\-]+$", name):
            return "❌ Niedozwolona nazwa modułu."
        script = self.base / (name + ".py")
        if not script.exists():
            return f"❌ Brak modułu: {script}"
        # Spróbuj najpierw rozpoznać komendę sprzętową
        hw_result = bridge.execute(name)
        if hw_result:
            print(f"[HARDWARE] {hw_result}")
            return hw_result
        cmd = ["python3", str(script)] + (args or [])
        try:
            p = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
            )
            out = p.stdout if p.returncode == 0 else (p.stderr or p.stdout)
            self.logger.log("module.run", module=name, rc=p.returncode, bytes=len(out.encode("utf-8")))
            return out.strip()
        except Exception as e:
            return f"❌ Błąd modułu: {e}"

# =================== MODULE RUNNER ===================
class ModuleRunner:
    """
    Ładowanie i uruchamianie prostych modułów z katalogu 'modules'.
    Moduł to:
      - plik:   modules/<nazwa>.py
      - albo pkg: modules/<nazwa>/__init__.py
    Wymagana funkcja: main(args) (args: lista lub None)
    Opcjonalnie: __doc__ do opisu.
    """
    def __init__(self, cfg: Config, logger: RotatingLogger, base_dir: str = "modules"):
        self.cfg = cfg
        self.logger = logger
        self.base = Path(base_dir)

    def _module_file(self, name: str) -> Optional[Path]:
        p_file = self.base / f"{name}.py"
        p_pkg = self.base / name / "__init__.py"
        if p_file.exists():
            return p_file
        if p_pkg.exists():
            return p_pkg
        return None

    def list(self) -> List[str]:
        mods: List[str] = []
        if not self.base.exists():
            return mods
        for p in self.base.iterdir():
            if p.is_file() and p.suffix == ".py":
                mods.append(p.stem)
            elif p.is_dir() and (p / "__init__.py").exists():
                mods.append(p.name)
        return sorted(mods)

    def run(self, name: str, args: str = "") -> Tuple[bool, str]:
        mf = self._module_file(name)
        if not mf:
            return False, f"❌ Brak modułu: {self.base / (name + '.py')}"
        try:
            spec = importlib.util.spec_from_file_location(f"modules.{name}", mf)
            if not spec or not spec.loader:
                return False, "❌ Nie mogę załadować spec modułu."
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            if not hasattr(mod, "main"):
                return False, "❌ Moduł nie ma funkcji main(args)"
            argv = shlex.split(args) if isinstance(args, str) else (args or [])
            res = mod.main(argv)
            return True, str(res) if res is not None else "✅ OK"
        except Exception as e:
            return False, f"❌ Błąd modułu: {e}"

    def info(self, name: str) -> str:
        mf = self._module_file(name)
        if not mf:
            return "❌ Brak modułu."
        try:
            spec = importlib.util.spec_from_file_location(f"modules.{name}", mf)
            if not spec or not spec.loader:
                return "❌ Nie mogę załadować spec modułu."
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[attr-defined]
            doc = getattr(mod, "__doc__", None)
            return (doc or "(brak opisu)").strip()
        except Exception as e:
            return f"❌ Błąd info: {e}"

# =================== GPTChatAPI (LLM + pamięć + tokeny + projekty + logi + sieć) ===================
class GPTChatAPI:
    def __init__(self, cfg: Config, session_id: str = "default"):
        self.cfg = cfg
        ensure_dirs(cfg)
        self.logger = RotatingLogger(cfg)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if OpenAI and os.getenv("OPENAI_API_KEY") else None
        self.validator = CommandValidator(cfg)
        self.exec = CommandExecutor(cfg, self.logger)
        self.projects = ProjectManager(cfg)
        self.files = FileOps(cfg, self.projects)
        self.memory = MemoryStore(cfg)
        self.meter = TokenMeter(cfg, self.logger)
        self.http = HttpTool(cfg, self.logger)
        self.git = GitManager(cfg, self.projects, self.logger)
        self.session_id = session_id
        self.memory.ensure_session(session_id)
        self.logger.log("agent.start", model=cfg.OPENAI_MODEL, usd_to_pln=cfg.USD_TO_PLN)
        self.modules = ModuleRunner(cfg, self.logger)

    # --------- Prompt budowany z pamięci i streszczeń ---------
    def _system_prompt(self) -> str:
        rules = [
            "Jesteś asystentem terminalowym i helperem do generowania kodu.",
            "Zasady:",
            "- Na pytania ogólne odpowiadaj tekstem.",
            "- Przy generowaniu kodu używaj WYŁĄCZNIE standardowej biblioteki Pythona.",
            "- Nie używaj pip/requests/keyboard/termcolor.",
            "- W kodzie nie zwracaj poleceń do shella ani komentarzy – tylko czysty blok ```python```.",

            # --- BLOK INTERNETOWY ---
            "Masz dostęp do narzędzi web_fetch oraz browser_query.",
            "Jeśli pytanie wymaga aktualnych danych (pogoda, kursy walut, notowania, newsy, fakty bieżące, dane o firmach, produktach, usługach, osobach, wydarzeniach) – użyj web_fetch.",
            "Jeśli użytkownik nie podał konkretnego URL, rozpocznij od wyszukiwarki Bing w formie: https://www.bing.com/search?q=<zapytanie>.",
            "Jeśli pytanie dotyczy pogody – użyj https://wttr.in/<miasto>?format=3.",
            "Jeśli pytanie dotyczy kursu USD/EUR – użyj API NBP, np. https://api.nbp.pl/api/exchangerates/rates/A/USD/?format=json.",
            "Po pobraniu danych użyj browser_query do analizy HTML (tytuł, linki, streszczenie).",
            "Odpowiedź pisz zwięźle, w języku naturalnym, na podstawie realnych danych z internetu.",
            "Nie pokazuj użytkownikowi tool-callów ani JSON – to działa tylko wewnętrznie.",

            # --- AUTOKOREKTA ZAPYTAŃ ---
            "Jeśli pytanie użytkownika zawiera literówki, błędy ortograficzne lub oczywiste pomyłki (imiona, nazwy firm, miast, produktów), popraw zapytanie w sposób dyskretny i użyj poprawionej wersji do wyszukiwania.",
            "Jeśli istnieje kilka możliwych poprawek, wybierz tę najbardziej prawdopodobną na podstawie kontekstu pytania.",

            # --- PRIORYTET RZETELNYCH ŹRÓDEŁ NEWSOWYCH ---
            "Podczas wyszukiwania aktualnych informacji i newsów, najpierw próbuj znaleźć dane w najbardziej zaufanych źródłach globalnych:",
            "1. Reuters (https://www.reuters.com)",
            "2. AP News (https://apnews.com)",
            "3. BBC News (https://www.bbc.com/news)",
            "Jeśli wyniki z tych źródeł są dostępne w wyszukiwaniu – traktuj je jako priorytetowe.",
            "Jeśli nie znajdziesz danych w tych źródeł, wtedy przechodź do wyników ogólnych wyszukiwarki.",

            # --- ANALIZA PLIKÓW I FOLDERÓW ---
            "Jeśli użytkownik prosi o analizę folderu:",
            "- najpierw użyj dir_list aby poznać zawartość.",
            "- wybierz tylko istotne pliki (.py, .json, .txt).",
            "- dla każdego użyj file_access lub file_chunk jeśli plik jest duży.",
            "- analizuj strukturę projektu na podstawie realnych plików.",
            "Jeśli użytkownik chce znaleźć miejsce w kodzie, użyj file_search.",
            "Jeśli użytkownik chce modyfikacji kodu, użyj file_write.",
            "Nigdy nie zgaduj treści plików — zawsze pobieraj je narzędziami.",
        ]

        # --- Stałe, użytkownikowe reguły z pliku ---
        extra_rules = load_persistent_prompt_rules()
        if extra_rules:
            rules.append("\nDodatkowe stałe reguły zachowania (z pliku):")
            for r in extra_rules:
                rules.append(r)

        pinned = self.memory.pinned_memories(self.session_id)
        if pinned:
            rules.append("\nStałe fakty (pinned), traktuj jak kontekst użytkownika:")
            for p in pinned:
                rules.append(f"- {p}")
        _, summary = self.memory.last_summary(self.session_id)
        if summary:
            rules.append("\nStreszczenie dotychczasowej rozmowy:")
            rules.append(summary[: self.cfg.SUMMARY_MAX_CHARS])
        return "\n".join(rules)

    # --------- Autostreszczenia po N wiadomościach ---------
    def _maybe_autosummarize(self):
        if not self.client:
            return
        cnt = self.memory.count_since_summary(self.session_id)
        if cnt < self.cfg.SUMMARY_MSG_THRESHOLD:
            return
        last_id, _ = self.memory.last_summary(self.session_id)
        msgs = self.memory.get_messages_since(self.session_id, last_id, limit=self.cfg.SUMMARY_WINDOW)
        if not msgs:
            return
        convo = []
        for m in msgs:
            convo.append(f"{m['role'].upper()}: {m['content']}")
        convo_text = "\n".join(convo)[-4000:]
        prompt = (
            "Stwórz zwięzłe streszczenie poniższej rozmowy, w 5-10 punktach, "
            "tylko najważniejsze fakty i decyzje użytkownika. Unikaj wodolejstwa.\n\n"
            + convo_text
        )
        try:
            resp = self.client.chat.completions.create(
                model=self.cfg.OPENAI_MODEL,
                temperature=0.2,
                max_tokens=400,
                messages=[
                    {"role": "system", "content": "Jesteś skrupulatnym narzędziem do streszczania."},
                    {"role": "user", "content": prompt},
                ],
            )
            summary = resp.choices[0].message.content.strip()
            upto = self.memory.last_message_id(self.session_id)
            self.memory.add_summary(self.session_id, upto, summary)
            self.logger.log("memory.summary.added", upto=upto, chars=len(summary))
            try:
                u = resp.usage
                self.meter.add_usage(
                    model=self.cfg.OPENAI_MODEL,
                    prompt_tokens=int(getattr(u, "prompt_tokens", 0)),
                    completion_tokens=int(getattr(u, "completion_tokens", 0)),
                    note="autosummary",
                )
            except Exception:
                pass
        except Exception as e:
            self.logger.log("memory.summary.error", error=str(e))

# --------- Deklaracja narzędzi (tools) dla GPT API ---------
    def _tools_schema(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Pobiera stronę internetową przez moduł hal_webfetch",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Adres URL lub zapytanie"
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_query",
                    "description": "Analizuje HTML strony jak tryb przeglądarki (browser-mode)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Adres URL, której dotyczy analiza"
                            },
                            "html": {
                                "type": "string",
                                "description": "Pełna treść HTML pobrana wcześniej przez web_fetch"
                            }
                        },
                        "required": ["url", "html"]
                    }
                }
            },
            {
            "type": "function",
            "function": {
                "name": "file_access",
                "description": "Czyta zawartość pliku z systemu użytkownika.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Ścieżka pliku do odczytu"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
    "type": "function",
    "function": {
        "name": "dir_list",
        "description": "Listuje pliki i katalogi w folderze",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "file_search",
        "description": "Przeszukuje treść plików we wskazanym katalogu",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "pattern": {"type": "string"}
            },
            "required": ["root", "pattern"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "file_chunk",
        "description": "Czyta fragment pliku od podanego offsetu",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "size": {"type": "integer"}
            },
            "required": ["path"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "file_write",
        "description": "Zapisuje treść do pliku",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    }
}
        ]

# --------- LLM interakcje ---------
    def ask_ai(self, prompt: str, *, execute: bool = True, note: str = "") -> str:
        if not self.client:
            return f"🔌 [Offline] Brak OPENAI_API_KEY. Prompt: {prompt}"

        # --- Budowa wiadomości ---
        msgs = [{"role": "system", "content": self._system_prompt()}]
        msgs += self.memory.get_recent_messages(self.session_id, limit=10)
        msgs.append({"role": "user", "content": prompt})

        # --- Log: request ---
        self.logger.log(
            "llm.request",
            model=self.cfg.OPENAI_MODEL,
            note=note,
            prompt_len=len(prompt)
        )

        # --- Call LLM z narzędziami ---
        resp = self.client.chat.completions.create(
            model=self.cfg.OPENAI_MODEL,
            temperature=self.cfg.OPENAI_TEMPERATURE,
            max_tokens=self.cfg.OPENAI_MAX_TOKENS,
            messages=msgs,
            tools=self._tools_schema(),
            tool_choice="auto",
        )

        # Odpowiedź może być None
        answer = resp.choices[0].message.content
        answer = answer.strip() if answer else ""

        # --- Obsługa tool-calls ---
        tool_calls = getattr(resp.choices[0].message, "tool_calls", None)
        if tool_calls:

            assistant_msg = {
                "role": "assistant",
                "content": answer,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            }

            final_messages = [
                {"role": "system", "content": self._system_prompt()},
            ]

            final_messages += self.memory.get_recent_messages(self.session_id, limit=10)
            final_messages.append({"role": "user", "content": prompt})
            final_messages.append(assistant_msg)

            # wykonanie narzędzi
            for call in tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments)

                # WEB FETCH
                if name == "web_fetch":
                    try:
                        out = registry.invoke("web_fetch", args)
                    except Exception as e:
                        out = {"error": str(e)}

                # BROWSER QUERY
                elif name == "browser_query":
                    try:
                        out = perform_browser_query(args["url"], args["html"])
                    except Exception as e:
                        out = {"error": str(e)}

                # FILE ACCESS (czytanie plików)
                elif name == "file_access":
                    try:
                        out = registry.invoke("file_access", args)
                    except Exception as e:
                        out = {"error": str(e)}

                # LISTOWANIE FOLDERU
                elif name == "dir_list":
                    try:
                        out = registry.invoke("dir_list", args)
                    except Exception as e:
                        out = {"error": str(e)}

                # PRZESZUKIWANIE PLIKÓW
                elif name == "file_search":
                    try:
                        out = registry.invoke("file_search", args)
                    except Exception as e:
                        out = {"error": str(e)}

                # CZYTANIE FRAGMENTÓW PLIKÓW
                elif name == "file_chunk":
                    try:
                        out = registry.invoke("file_chunk", args)
                    except Exception as e:
                        out = {"error": str(e)}

                # ZAPIS DO PLIKU
                elif name == "file_write":
                    try:
                        out = registry.invoke("file_write", args)
                    except Exception as e:
                        out = {"error": str(e)}

                # nieznane narzędzie
                else:
                    out = {"error": f"Unknown tool {name}"}

                # wymuszenie tekstu
                if isinstance(out, (dict, list)):
                    out_str = json.dumps(out, ensure_ascii=False)
                else:
                    out_str = str(out)

                final_messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": out_str,
                })

            resp2 = self.client.chat.completions.create(
                model=self.cfg.OPENAI_MODEL,
                temperature=self.cfg.OPENAI_TEMPERATURE,
                max_tokens=self.cfg.OPENAI_MAX_TOKENS,
                messages=final_messages,
            )

            return resp2.choices[0].message.content.strip()

        # --- Log: odpowiedź ---
        self.logger.log(
            "llm.response",
            model=self.cfg.OPENAI_MODEL,
            answer_len=len(answer)
        )

        # --- Tokeny ---
        try:
            u = resp.usage
            self.meter.add_usage(
                model=self.cfg.OPENAI_MODEL,
                prompt_tokens=int(getattr(u, "prompt_tokens", 0)),
                completion_tokens=int(getattr(u, "completion_tokens", 0)),
                note=note or ("execute" if execute else "noexec"),
            )
        except Exception:
            pass

        # --- Historia ---
        self.memory.add_message(self.session_id, "user", prompt)
        self.memory.add_message(self.session_id, "assistant", answer)
        self._maybe_autosummarize()

        # --- AUTO-WYKONANIE ---
        if execute:
            low = answer.lower()

            # Format 1: "wykonaj: <cmd>"
            if low.startswith("wykonaj:"):
                cmd = answer.split(":", 1)[1].strip()
                ok, warn = self.validator.validate(cmd)
                if not ok:
                    return warn or "❌ Komenda zablokowana."
                _, out = self.exec.run(cmd)
                return out

            # Format 2: ```bash ...```
            m = re.search(
                r"```(?:bash|sh)?\s*([\s\S]*?)```",
                answer,
                re.IGNORECASE
            )
            if m:
                cmd = m.group(1).strip()
                ok, warn = self.validator.validate(cmd)
                if not ok:
                    return warn or "❌ Komenda zablokowana."
                _, out = self.exec.run(cmd)
                return out

        return answer

    def device_command(self, text: str) -> str | None:
        """
        Rozpoznaje i wykonuje polecenie sprzętowe przez HardwareBridge.
        Zwraca wynik tekstowy lub None, jeśli nie rozpoznano.
        """
        try:
            result = bridge.execute(text)
            if result:
                print(f"[HARDWARE] {result}")
            return result
        except Exception as e:
            print(f"[hardware_bridge error] {e}")
            return None

    # --------- CODE: generuj → napraw → zapisz → auto-commit → uruchom ---------
    def generate_and_run_code(self, prompt: str, filename: Optional[str] = None) -> str:
        # --- FAZA 2: analiza promptu ---
        try:
            from modules import intelligence
            analysis = intelligence.analyze_prompt(prompt)
            task_type = analysis["type"]
            profile = analysis["profile"]
            expected_output = analysis["expected_output"]
            print(f"[INTELIGENCE] typ={task_type}, profil={profile}, wynik={expected_output}")
        except Exception as e:
            print(f"[INTELIGENCE] błąd analizy: {e}")
            analysis = {"type": "text", "profile": "headless", "expected_output": "tekst"}
            profile = "headless"
        # --- Analiza promptu i ustalenie profilu sandboxa ---
        task_meta = None
        profile = "headless"
        expected_output = None
        if 'intelligence' in globals() and intelligence:
            try:
                task_meta = intelligence.analyze_prompt(prompt)
                profile = task_meta.get("profile", "headless")
                expected_output = task_meta.get("expected_output")
                task_type = task_meta.get("type")
                self._last_task_meta = task_meta  # opcjonalnie: zapamiętaj do diagnostyki
                print(f"[INTELLIGENCE] Typ: {task_type}, Profil: {profile}, Cel: {expected_output}")
            except Exception as e:
                print(f"[INTELLIGENCE] Błąd analizy promptu: {e}")
                profile = "headless"
                expected_output = None

        self.logger.log("code.gen.start", prompt_len=len(prompt))
        raw = self.ask_ai(prompt, execute=False, note="code_gen")
        code = sanitize_llm_code(raw)

        # Preflight i auto-naprawa
        attempts = 0
        max_attempts = 2
        err = compile_check(code)
        missing = missing_third_party(code)
        while (err or missing) and attempts < max_attempts:
            attempts += 1
            self.logger.log("code.gen.fix_attempt", attempt=attempts, err=bool(err), missing=",".join(missing))
            fix_raw = self.ask_ai(repair_prompt(code, err or "", missing), execute=False, note="code_fix")
            code = sanitize_llm_code(fix_raw)
            err = compile_check(code)
            missing = missing_third_party(code)

        # Nazwa pliku
        if not filename:
            ts = time.strftime("%Y%m%d_%H%M%S")
            filename = f"ai_code_{ts}.py"

        # Zapis do sandboxa projektu
        if not self.files.write(filename, code):
            self.logger.log("code.save.error", filename=filename)
            return f"❌ Nie udało się zapisać pliku (sandbox): {filename}"
        abs_target = self.projects.current_path() / filename
        print(f"💾 Zapisano kod do {abs_target}")
        self.logger.log("code.save.ok", path=str(abs_target), bytes=len(code.encode('utf-8')))

        # --- FAZA 3b: rejestracja wygenerowanego kodu ---
        if 'code_registry' in globals() and code_registry and abs_target and os.path.exists(abs_target):
            try:
                rec = code_registry.register_path(
                    abs_target,
                    project=(getattr(self, "active_project", None) or "sandbox"),
                    meta=getattr(self, "_last_task_meta", None)
                )
                print(f"[REGISTRY] Zarejestrowano plik: {rec['file']} (SHA256={rec['sha256'][:8]})")
                code_registry.git_autocommit(
                    os.path.relpath(abs_target, Path.home() / "HALbridge"),
                    f"auto: code generated {rec['project']}"
                )
            except Exception as e:
                print(f"[REGISTRY] Błąd rejestracji: {e}")

        # Auto-commit po zapisie
        try:
            self.git.autocommit(f"codegen: {filename}")
        except Exception:
            pass

        # Sprawdzenie składni
        syn = compile_check(code)
        if syn:
            self.logger.log("code.compile.error", err=syn)
            return f"❌ Błąd komp.: {syn}"

        # Uruchom wg rozszerzenia
        low = str(abs_target).lower()
        if low.endswith(".py"):
            run_cmd = f"python3 {shlex.quote(str(abs_target))}"
        elif low.endswith((".sh", ".bash")):
            try:
                st = os.stat(abs_target)
                os.chmod(abs_target, st.st_mode | stat.S_IEXEC)
            except Exception:
                pass
            run_cmd = f"bash {shlex.quote(str(abs_target))}"
        else:
            return "ℹ️ Plik zapisany, ale rozszerzenie nieznane – nie uruchamiam."

        ok, warn = self.validator.validate(run_cmd)
        if not ok:
            self.logger.log("code.run.blocked", cmd=run_cmd, reason=warn)
            return warn or "❌ Komenda zablokowana."
        success, out = self.exec.run(run_cmd)

        # Jedna próba auto-fix po runtime errorze
        if not success and ("Traceback (most recent call last):" in out or "ModuleNotFoundError" in out or "ImportError" in out):
            self.logger.log("code.runtime.error", cmd=run_cmd)
            fix_raw = self.ask_ai(repair_prompt(code, out, missing_third_party(code)), execute=False, note="code_runtime_fix")
            code2 = sanitize_llm_code(fix_raw)
            if code2 and code2 != code:
                if not self.files.write(filename, code2):
                    self.logger.log("code.runtime.save_error", filename=filename)
                    return f"❌ Nie udało się zapisać poprawki (sandbox): {filename}"
                print(f"🔁 Poprawka zapisana do {abs_target}, uruchamiam ponownie...")
                syn2 = compile_check(code2)
                if syn2:
                    self.logger.log("code.runtime.compile_error", err=syn2)
                    return f"❌ Błąd kompilacji po poprawce: {syn2}"
                _, out2 = self.exec.run(run_cmd)
                return out2
        return out


# =================== CLI MAIN ===================
def banner(cfg: Config, api: GPTChatAPI):
    print("🌐 GPT TERMINAL v3 — 'exit' aby zakończyć")
    print("📁 read <plik> — odczyt pliku (domyślnie w aktualnym projekcie)")
    print("✏️ write <plik> <treść> — zapis pliku (sandbox)")
    print("🧠 ai <prompt> — rozmowa z LLM (bez wykonania)")
    print("🧩 code [plik.py] <prompt> — wygeneruj kod, preflight, auto-naprawa, uruchom (w projekcie)")
    print("📡 !komenda — wykonanie systemowe (bez NLP)")
    print("📦 project list | new <nazwa> | open <nazwa> | pwd — zarządzanie projektami")
    print("🧠 mem add <tekst> | mem list [N] | mem search <query> | mem pin <id> | mem unpin <id> | mem clear")
    print("🧾 logs tail [N] — ostatnie N linii loga (domyślnie 100)")
    print("💳 tokens — pokaż łączny koszt i tokeny")
    print("🌐 net on|off | allow <dom> | deny <dom> | list | get <URL> [--headers]")
    print("🔧 vcs init | status | log [N] | diff [plik] | commit \"msg\" — kontrola wersji (git)")
    print(f"⚙️ STRICT={'ON' if cfg.STRICT_MODE else 'OFF'} — wszystko inne traktuję jako komendę NLP→bash")
    print(f"📂 Projekt: {api.projects.current_name()}  @  {api.projects.current_path()}")
    print(f"💳 Cennik (USD/1k): {json.dumps(cfg.MODEL_PRICING.get(cfg.OPENAI_MODEL, {}))} | Kurs: {cfg.USD_TO_PLN} PLN/USD")
    print("ℹ️ help — skrót poleceń | about — wersja i model")
    print(f"🛠️ STRICT={ 'ON' if cfg.STRICT_MODE else 'OFF' } | MODEL={cfg.OPENAI_MODEL} | T={cfg.OPENAI_TEMPERATURE} | MAXTOK={cfg.OPENAI_MAX_TOKENS}")
    print("📌 Dostępne modele: gpt-4o | gpt-4o-mini | gpt-4.1 | gpt-4.1-mini | gpt-3.5-turbo")
    print(api.meter.summary())

def main():
    cfg = Config()
    ensure_dirs(cfg)

    # Pobranie klucza jeśli brak
    if not os.getenv("OPENAI_API_KEY") and OpenAI:
        try:
            key = input("🔐 Brak OPENAI_API_KEY. Podaj klucz: ").strip()
            os.environ["OPENAI_API_KEY"] = key
        except EOFError:
            print("\n👋 Do zobaczenia (EOF).")
            return

    api = GPTChatAPI(cfg, session_id="local")
    banner(cfg, api)

# Rejestracja narzędzi Intent Engine
    registry.register("mqtt", "modules.tools.adapters.mqtt")

    # --- helper potwierdzeń dla ostrzeżeń ---
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

    while True:
        try:
            line = input("hal@agent:~$ ").strip()
            if not line:
                continue

            low = line.lower()

            # --- KOMENDA: zapamiętaj <tekst> ---
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

            # --- PRIORYTET 1: natywne komendy JSON (hardware_bridge) ---
            hw = api.device_command(line)
            if hw:
                continue

            # --- PRIORYTET 2: Intent Engine ---
            ie = intent_pipeline(line)

            if "ask" in ie:
                print(ie["ask"])
                continue

            if "plan" in ie:
                plan = ie["plan"]
                module = plan.get("module")

                if module == "hardware_bridge":
                    payload = {
                        "topic": "shelly/test",
                        "payload": plan.get("slots", {})
                    }
                    result = registry.invoke("mqtt", payload)
                    print("OK:", result)
                    continue

            # --- interceptor dla !py-mode (interactive | capture) ---
            _mode = handle_console_line_py_mode(line)
            if _mode is not None:
                if _mode:
                    print(_mode)
                continue

            # --- interceptor dla !py ---
            _py = handle_console_line_py(line)
            if _py is not None:
                if _py:
                    print(_py)
                continue

            # Wyjście
            if line.lower() in ("exit", "quit", "q"):
                print("👋 Do zobaczenia.")
                break

            # Pomoc / meta
            if line in ("help", "?"):
                print(show_help())
                continue

            if line == "about":
                print(f"🤖 Agent {APP_VERSION} | Model: {cfg.OPENAI_MODEL} | T={cfg.OPENAI_TEMPERATURE} | MAXTOK={cfg.OPENAI_MAX_TOKENS}")
                continue

            # STRICT on/off
            if line == "strict on":
                cfg.STRICT_MODE = True
                print("✅ STRICT: ON")
                continue

            if line == "strict off":
                cfg.STRICT_MODE = False
                print("✅ STRICT: OFF")
                continue

            # Zmiana modelu/temperatury/max_tokens
            if line.startswith("model "):
                name = line.split(" ", 1)[1].strip()
                if not name:
                    print("❌ Podaj nazwę modelu, np. model gpt-4o-mini")
                    continue
                cfg.OPENAI_MODEL = name
                print(f"✅ Ustawiono model: {name}")
                continue

            if line.startswith("temp "):
                try:
                    t = float(line.split(" ", 1)[1].strip())
                    if not (0.0 <= t <= 1.0):
                        raise ValueError()
                    cfg.OPENAI_TEMPERATURE = t
                    print(f"✅ Ustawiono temperaturę: {t}")
                except Exception:
                    print("❌ Podaj liczbę 0.0–1.0, np. temp 0.2")
                continue

            if line.startswith("max_tokens "):
                try:
                    mt = int(line.split(" ", 1)[1].strip())
                    if mt <= 0:
                        raise ValueError()
                    cfg.OPENAI_MAX_TOKENS = mt
                    print(f"✅ Ustawiono max_tokens: {mt}")
                except Exception:
                    print("❌ Podaj dodatnią liczbę całkowitą, np. max_tokens 1200")
                continue

            # Projekty
            if line == "project list":
                    break

            # --- GRAFICZNA PRZEGLĄDARKA (BrowserBridge) ---
            low = line.lower().strip()
            if low.startswith(("otwórz ", "otworz ", "pokaż stronę", "pokaz strone", "otwórz stronę", "open ")):
                if browser:
                    print(browser.open(line))
                else:
                    print("❌ BrowserBridge nie jest dostępny")
                continue

            # Files
            if line.startswith("read "):
                path = line[5:].strip()
                txt = api.files.read(path)
                print(txt if txt is not None else "❌ Nie udało się odczytać (sandbox)")
                continue

            if line.startswith("write "):
                parts = shlex.split(line)
                if len(parts) >= 3:
                    path = parts[1]
                    content = " ".join(parts[2:])
                    ok = api.files.write(path, content)
                    print("✅ Zapisano" if ok else "❌ Błąd zapisu (sandbox)")
                else:
                    print("❌ Składnia: write <plik> <treść>")
                continue

            # Memories
            if line.startswith("mem add "):
                txt = line[len("mem add "):].strip()
                mid = api.memory.add_memory(api.session_id, txt, kind="note", pinned=False)
                print(f"✅ Dodano pamięć #{mid}")
                continue

            if line.startswith("mem pin "):
                try:
                    mid = int(line[len("mem pin "):].strip())
                    api.memory.pin_memory(mid, True)
                    print(f"✅ Przypięto pamięć #{mid}")
                except Exception:
                    print("❌ Składnia: mem pin <id>")
                continue

            if line.startswith("mem unpin "):
                try:
                    mid = int(line[len("mem unpin "):].strip())
                    api.memory.pin_memory(mid, False)
                    print(f"✅ Odpięto pamięć #{mid}")
                except Exception:
                    print("❌ Składnia: mem unpin <id>")
                continue

            if line.startswith("mem search "):
                q = line[len("mem search "):].strip()
                rows = api.memory.search_memories(api.session_id, q, limit=20)
                if not rows:
                    print("(brak wyników)")
                else:
                    for r in rows:
                        pin = "📌" if r["pinned"] else "  "
                        print(f"{pin} #{r['id']} [{r['kind']}] {r['created_at']}\n  {r['content']}")
                continue

            if line.startswith("mem list"):
                parts = shlex.split(line)
                n = 20
                if len(parts) == 3 and parts[2].isdigit():
                    n = int(parts[2])
                rows = api.memory.list_memories(api.session_id, limit=n)
                if not rows:
                    print("(pusto)")
                else:
                    for r in rows:
                        pin = "📌" if r["pinned"] else "  "
                        print(f"{pin} #{r['id']} [{r['kind']}] {r['created_at']}\n  {r['content']}")
                continue

            if line == "mem clear":
                cnt = api.memory.clear_memories(api.session_id)
                print(f"🗑️ Usunięto {cnt} wpisów pamięci")
                continue

            # Logi
            if line.startswith("logs tail"):
                parts = shlex.split(line)
                n = 100
                if len(parts) == 3 and parts[2].isdigit():
                    n = int(parts[2])
                print(api.logger.tail(n))
                continue

            if line.startswith("logs grep "):
                pattern = line[len("logs grep "):].strip()
                path = Path(cfg.APP_LOG_FILE)
                if not path.exists():
                    print("(brak logów)")
                else:
                    pat = re.compile(pattern, re.IGNORECASE)
                    cnt = 0
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        for L in f:
                            if pat.search(L):
                                print(L.rstrip())
                                cnt += 1
                    if cnt == 0:
                        print("(brak trafień)")
                continue

            if line.startswith("logs export "):
                outp = line[len("logs export "):].strip()
                srcp = Path(cfg.APP_LOG_FILE)
                if not srcp.exists():
                    print(" ❌ Brak logów do eksportu")
                else:
                    try:
                        Path(outp).parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(srcp, outp)
                        print(f"✅ Wyeksportowano do {outp}")
                    except Exception as e:
                        print(f"❌ Błąd eksportu: {e}")
                continue

            if line == "logs clear":
                try:
                    Path(cfg.APP_LOG_FILE).unlink(missing_ok=True)
                    for i in range(1, cfg.LOG_BACKUPS + 1):
                        Path(f"{cfg.APP_LOG_FILE}.{i}").unlink(missing_ok=True)
                    print("🧹 Logi wyczyszczone")
                except Exception as e:
                    print(f"❌ Błąd czyszczenia: {e}")
                continue

            # DIAG (krok 3)
            if line == "diag":
                api.logger.log(
                    "diag.run",
                    project=api.projects.current_name(),
                    model=cfg.OPENAI_MODEL,
                    strict=cfg.STRICT_MODE,
                    net=cfg.ENABLE_NETWORK_OPS,
                )
                print(render_diag(cfg, api))
                continue

            # Tokeny / Meter (krok 4)
            if line == "tokens":
                print(api.meter.summary())
                continue

            if line == "tokens report":
                print(api.meter.report())
                continue

            if line == "tokens reset":
                api.meter.reset()
                print("✅ Liczniki tokenów wyzerowane.")
                continue

            # VCS / Git (krok 5)
            if line == "vcs init":
                print(api.git.init())
                continue

            if line == "vcs ensure":
                print(api.git.init())
                continue

            if line == "vcs status":
                print(api.git.status())
                continue

            if line.startswith("vcs oneline"):
                parts = shlex.split(line)
                n = 20
                if len(parts) >= 3 and parts[2].isdigit():
                    n = int(parts[2])
                print(api.git.log(n))
                continue

            if line.startswith("vcs diff"):
                parts = shlex.split(line)
                path_arg = parts[2] if len(parts) >= 3 else None
                print(api.git.diff(path_arg))
                continue

            if line.startswith("vcs save:"):
                msg = line.split(":", 1)[1].strip()
                if not msg:
                    print('❌ Podaj komunikat, np. vcs save: "komentarz"')
                else:
                    print(api.git.commit(msg))
                continue

            if line.startswith("vcs commit "):
                msg = line[len("vcs commit "):].strip().strip('"').strip("'")
                if not msg:
                    print('❌ Podaj komunikat: vcs commit "wiadomość"')
                else:
                    print(api.git.commit(msg))
                continue

            # ===== Modules =====
            if line == "modules list":
                mods = api.modules.list()
                if mods:
                    print("Dostępne moduły:")
                    for m in mods:
                        print(f"- {m}")
                else:
                    print("(brak modułów)")
                continue

            if line.startswith("module info "):
                parts = shlex.split(line)
                if len(parts) >= 3:
                    name = parts[2]
                    print(api.modules.info(name))
                else:
                    print("❌ Składnia: module info <nazwa>")
                continue

            if line.startswith("module run "):
                parts = shlex.split(line)
                if len(parts) >= 3:
                    name = parts[2]
                    args = " ".join(parts[3:])
                    ok, out = api.modules.run(name, args)
                    print(out)
                else:
                    print("❌ Składnia: module run <nazwa> [args...]")
                continue

            # Sieć i GET
            if line == "net on":
                cfg.ENABLE_NETWORK_OPS = True
                print("🌐 Sieć: ON")
                continue

            if line == "net off":
                cfg.ENABLE_NETWORK_OPS = False
                print("🌐 Sieć: OFF")
                continue

            if line.startswith("net allow "):
                dom = line[len("net allow "):].strip().lower()
                if dom:
                    cfg.NET_ALLOWED.add(dom)
                    print(f"✅ Dodano do whitelist: {dom}")
                else:
                    print("❌ Podaj domenę")
                continue

            if line.startswith("net deny "):
                dom = line[len("net deny "):].strip().lower()
                if dom and dom in cfg.NET_ALLOWED:
                    cfg.NET_ALLOWED.remove(dom)
                    print(f"✅ Usunięto z whitelist: {dom}")
                else:
                    print("❌ Domena nie jest na whitelist")
                continue

            if line == "net list":
                wl = sorted(cfg.NET_ALLOWED) or ["(pusto)"]
                print("Dozwolone domeny:")
                print("\n".join(f"- {d}" for d in wl))
                print(f"Status: {'ON' if cfg.ENABLE_NETWORK_OPS else 'OFF'} | timeout={cfg.NET_TIMEOUT}s | max={cfg.NET_MAX_BYTES}B")
                continue

            if line.startswith("geth "):
                parts = shlex.split(line)
                if len(parts) >= 2:
                    url = parts[1]
                    print(api.http.get(url, want_headers=True))
                else:
                    print("❌ Składnia: geth <URL>")
                continue

            if line.startswith("get "):
                parts = shlex.split(line)
                if len(parts) >= 2:
                    url = parts[1]
                    want_headers = ("--headers" in parts)
                    print(api.http.get(url, want_headers=want_headers))
                else:
                    print("❌ Składnia: get <URL> [--headers]")
                continue
                continue
            if low in ("yt play", "yt pause", "yt pp"):
                print(browser.yt_play_pause())
                continue
            if low in ("yt next", "yt n"):
                print(browser.yt_next())
                continue
            if low in ("yt prev", "yt p"):
                print(browser.yt_prev())
                continue
            if low in ("yt vol+", "yt up"):
                print(browser.yt_volume_up())
                continue
            if low in ("yt vol-", "yt down"):
                print(browser.yt_volume_down())
                continue
            if low in ("yt mute",):
                print(browser.yt_mute())
                continue
            if low in ("yt fs", "yt fullscreen"):
                print(browser.yt_fullscreen())
                continue
            # --- Natural web query (OPCJA B) ---
            url = resolve_natural_query(line)
            if url:
                result = registry.invoke("web_fetch", {"url": url})
                print(result)
                continue

            # --- Explicit 'web <URL>' (OPCJA B) ---
            if line.startswith("web "):
                url = line[4:].strip()
                result = registry.invoke("web_fetch", {"url": url})
                print(result)
                continue
            # --- Tryb przeglądarkowy (tylko dla rzeczywistych stron WWW) ---
            if line.startswith(("otwórz", "pokaż", "znajdź", "wyszukaj")):
                low = line.lower()

                # heurystyka: czy to wygląda na operację na plikach / katalogach?
                looks_like_fs = (
                    any(word in low for word in ["folder", "katalog", "plik", "katalogu", "folderu", "pliku"])
                    or any(ch in line for ch in ["/", "\\", "~"])
                )

                # heurystyka: czy to wygląda na URL / stronę WWW?
                looks_like_url = (
                    "http://" in low
                    or "https://" in low
                    or "www." in low
                    or "stronę" in low
                    or "strone" in low
                    or "strona " in low
                    # coś.tld / coś.tld/coś
                    or bool(re.search(r"\.[a-z]{2,4}(/|$|\s)", low))
                )

                # Jeśli to ewidentnie URL/strona i NIE wygląda na ścieżkę plikową → przeglądarka
                if looks_like_url and not looks_like_fs:
                    print(browser.open(line))
                    continue

                # W przeciwnym razie NIE wymuszamy przeglądarki.
                # Komenda spadnie dalej do logiki STRICT / LLM / tools.
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
                                f.write(f"[{datetime.now(tz=tz.utc).isoformat(timespec='seconds')}] WARN-SKIP: {warn} for: {cmd}\n---\n")
                        except Exception:
                            pass
                        print("⏭️ Pominięto.")
                        continue
                # Spróbuj najpierw komendę sprzętową (hardware bridge)
                hw_result = bridge.execute(cmd)
                if hw_result:
                    print(hw_result)
                    continue
                success, out = api.exec.run(cmd, warn=warn)
                print(out)
                continue

            # AI
            if line.startswith("ai "):
                prompt = line[3:].strip()
                print(api.ask_ai(prompt, execute=False, note="ai"))
                print(api.meter.summary())
                continue

            # CODE
            if line.startswith("code "):
                rest = line[5:].strip()
                filename = None
                m = re.match(r'^([A-Za-z0-9_\-./]+?\.(?:py|sh|bash))\s*:\s*(.*)$', rest)
                if m:
                    filename, pr = m.group(1), m.group(2).strip()
                else:
                    parts = rest.split(maxsplit=1)
                    if len(parts) == 2 and re.match(r'^[A-Za-z0-9_\-./]+?\.(?:py|sh|bash)$', parts[0]):
                        filename, pr = parts[0], parts[1].strip()
                    else:
                        pr = rest
                print(api.generate_and_run_code(pr, filename=filename))
                print(api.meter.summary())
                continue

            # STRICT: wszystko inne = komenda systemowa
            if cfg.STRICT_MODE:
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

            # Fallback: rozmowa
            print(api.ask_ai(line, execute=False, note="fallback"))
            print(api.meter.summary())

        except KeyboardInterrupt:
            print("\n⏹️ Przerwano. 'exit' aby zakończyć.")
        except EOFError:
            print("\n👋 Do zobaczenia (EOF).")
            break
        except Exception as e:
            print(f"❌ Błąd: {e}")

if __name__ == "__main__":
    main()
