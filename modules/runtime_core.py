from __future__ import annotations

import csv
import json
import os
import re
import platform
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone as tz
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

try:
    import requests
except Exception:
    requests = None

try:
    import psutil
except Exception:
    psutil = None

try:
    import getpass
except Exception:
    getpass = None

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
        last_cost_usd = (prompt_tokens / 1000) * usd_in + (completion_tokens / 1000) * usd_out
        last_cost_pln = last_cost_usd * self.cfg.USD_TO_PLN
        totals.update(
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=cost_usd,
            cost_pln=cost_pln,
            calls=calls,
            last_model=model,
            last_prompt_tokens=prompt_tokens,
            last_completion_tokens=completion_tokens,
            last_total_tokens=prompt_tokens + completion_tokens,
            last_cost_usd=last_cost_usd,
            last_cost_pln=last_cost_pln,
            last_note=note or "",
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

        lpt = int(t.get("last_prompt_tokens", 0))
        lct = int(t.get("last_completion_tokens", 0))
        ltt = int(t.get("last_total_tokens", lpt + lct))
        lusd = float(t.get("last_cost_usd", 0.0))
        lpln = float(t.get("last_cost_pln", 0.0))
        lmodel = str(t.get("last_model", "") or "")
        lnote = str(t.get("last_note", "") or "")

        base = f"🔢 Tokeny: prompt={pt}, completion={ct} | 💵 Koszt: {usd:.4f} USD ~ {pln:.2f} PLN | 📞 Wywołań: {calls}, Średnio/tokeny: {avg_tokens:.1f}"

        if calls <= 0:
            return base

        last = f"🧷 Ostatnio: prompt={lpt}, completion={lct}, suma={ltt} | koszt: {lusd:.4f} USD ~ {lpln:.2f} PLN"
        if lmodel:
            last += f" | model={lmodel}"
        if lnote:
            last += f" | note={lnote}"

        return base + "\n" + last

    def reset(self):
        """Wyzeruj liczniki zużycia (sumy w JSON)."""
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "cost_pln": 0.0,
            "calls": 0,
            "last_model": "",
            "last_prompt_tokens": 0,
            "last_completion_tokens": 0,
            "last_total_tokens": 0,
            "last_cost_usd": 0.0,
            "last_cost_pln": 0.0,
            "last_note": "",
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

        lpt = int(t.get("last_prompt_tokens", 0))
        lct = int(t.get("last_completion_tokens", 0))
        ltt = int(t.get("last_total_tokens", lpt + lct))
        lusd = float(t.get("last_cost_usd", 0.0))
        lpln = float(t.get("last_cost_pln", 0.0))
        lmodel = str(t.get("last_model", "") or "")
        lnote = str(t.get("last_note", "") or "")

        out = (
            f"=== RAPORT TOKENÓW ===\n"
            f"Prompt: {pt}\n"
            f"Completion: {ct}\n"
            f"Suma: {total_tokens}\n"
            f"Wywołań: {calls}\n"
            f"Średnio/tokeny na wywołanie: {avg_tokens:.1f}\n"
            f"Koszt: {usd:.4f} USD ~ {pln:.2f} PLN\n"
        )

        if calls > 0:
            out += (
                f"\n=== OSTATNIA OPERACJA ===\n"
                f"Model: {lmodel or '-'}\n"
                f"Prompt: {lpt}\n"
                f"Completion: {lct}\n"
                f"Suma: {ltt}\n"
                f"Koszt: {lusd:.4f} USD ~ {lpln:.2f} PLN\n"
                f"Note: {lnote or '-'}\n"
            )

        return out

# =================== PROJECTS + SANDBOX ===================


