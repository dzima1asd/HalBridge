from __future__ import annotations

import os
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def playwright_python() -> str:
    env = os.getenv("HALBRIDGE_PLAYWRIGHT_PY")
    if env:
        return env

    root = project_root()
    candidate = root / ".venv_playwright" / "bin" / "python"
    if candidate.exists():
        return str(candidate)

    return sys.executable


def hal_webfetch_path() -> str:
    env = os.getenv("HALBRIDGE_WEBFETCH_SCRIPT")
    if env:
        return env

    root = project_root()
    candidate = root / "hal_webfetch.py"
    return str(candidate)
