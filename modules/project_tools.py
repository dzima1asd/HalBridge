from __future__ import annotations
import re
from typing import Optional, Tuple
from modules.runtime_core import RotatingLogger, ensure_dirs
from typing import List
from pathlib import Path
from modules.runtime_core import Config, ensure_dirs
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


