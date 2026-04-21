from __future__ import annotations
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from modules.runtime_core import Config, RotatingLogger
from datetime import datetime, timezone as tz
from modules.project_tools import ProjectManager
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
import os
import re
import json
import time
import shlex
import stat
import subprocess
import urllib.request
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
            if info == "❌ Nieprawidłowy URL":
                return info
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


