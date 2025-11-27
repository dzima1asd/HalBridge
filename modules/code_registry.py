#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Plik: ~/HALbridge/modules/code_registry.py

from __future__ import annotations
import json, os, hashlib, time, subprocess
from pathlib import Path
from typing import Optional, Dict

BASE = Path.home() / "HALbridge"
PROJECTS = BASE / "projects"
DATA_DIR = Path.home() / ".local" / "share" / "halbridge"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REG_PATH = DATA_DIR / "code_registry.json"        # append JSON-lines
DEFAULT_PROJECT = "sandbox"

def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def ensure_project(project: Optional[str]) -> Path:
    name = (project or DEFAULT_PROJECT).strip() or DEFAULT_PROJECT
    safe = "".join(c for c in name if c.isalnum() or c in "-_").lower()
    p = PROJECTS / safe
    p.mkdir(parents=True, exist_ok=True)
    return p

def save_artifact(content: str, *, project: Optional[str], filename: Optional[str], meta: Optional[Dict]=None) -> Dict:
    """Zapisuje plik do projects/<project>/<filename> (albo datowany), dopisuje wpis do rejestru."""
    proj_dir = ensure_project(project)
    if not filename:
        filename = f"code_{int(time.time())}.py"
    target = proj_dir / filename
    data = content.encode("utf-8")
    target.write_bytes(data)

    rec = {
        "ts": _now(),
        "project": proj_dir.name,
        "file": str(target),
        "sha256": _sha256(data),
        "size": len(data),
        "meta": meta or {},
    }
    with REG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec

def register_path(path: str, *, project: Optional[str], meta: Optional[Dict]=None) -> Dict:
    """Rejestruje istniejący plik na dysku jako artefakt projektu."""
    proj_dir = ensure_project(project)
    src = Path(path).expanduser().resolve()
    data = src.read_bytes()
    rec = {
        "ts": _now(),
        "project": proj_dir.name,
        "file": str(src),
        "sha256": _sha256(data),
        "size": len(data),
        "meta": meta or {},
    }
    with REG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec

def git_autocommit(path_in_repo: str, message: str) -> bool:
    """Opcjonalny auto-commit: wywołuje git add/commit w katalogu repo. Zwraca True/False."""
    try:
        repo = BASE  # zakładamy, że HALbridge jest repo
        if not (repo / ".git").exists():
            return False
        subprocess.run(["git", "-C", str(repo), "add", path_in_repo], check=False)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", message], check=False)
        return True
    except Exception:
        return False

# Prosty CLI:
if __name__ == "__main__":
    import argparse, sys
    ap = argparse.ArgumentParser(description="HALbridge Code Registry (Phase 3)")
    ap.add_argument("--project", default=DEFAULT_PROJECT)
    ap.add_argument("--file", help="Ścieżka do istniejącego pliku do rejestracji")
    ap.add_argument("--save-from-stdin", action="store_true", help="Zapisz stdin jako plik w projects/<project>/...")
    ap.add_argument("--name", help="Nazwa pliku docelowego (opcjonalnie przy --save-from-stdin)")
    ap.add_argument("--git-msg", help="Wykonaj git commit z tym komunikatem")
    args = ap.parse_args()

    if args.file:
        rec = register_path(args.file, project=args.project, meta={"src": "cli"})
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        if args.git_msg:
            git_autocommit(os.path.relpath(args.file, BASE), args.git_msg)
        sys.exit(0)

    if args.save_from_stdin:
        payload = sys.stdin.read()
        rec = save_artifact(payload, project=args.project, filename=args.name, meta={"src": "stdin"})
        print(json.dumps(rec, indent=2, ensure_ascii=False))
        if args.git_msg:
            rel = os.path.relpath(rec["file"], BASE)
            git_autocommit(rel, args.git_msg)
        sys.exit(0)

    ap.print_help()
    sys.exit(2)


# [AUTO-EXTEND Fallback]
# dodaj funkcję print_hello() wypisującą 'Witaj, Jaśnie Panie' ~/HALbridge/modules/code.py > /tmp/code.new && mv /tmp/code.new ~/HALbridge/modules/code.py

# [AUTO-EXTEND Fallback]
# dodaj funkcję print_hello() wypisującą 'Witaj, Jaśnie Panie' ~/HALbridge/modules/code.py > /tmp/code.new && mv /tmp/code.new ~/HALbridge/modules/code.py

def print_hello():
    print("Witaj, Jaśnie Panie!")


# testowy patch
