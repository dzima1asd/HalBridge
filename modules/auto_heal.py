#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import json, time
try:
    from modules.bus import BUS
except Exception:
    BUS = None

DATA = Path.home() / ".local" / "share" / "halbridge"
DATA.mkdir(parents=True, exist_ok=True)
LOG = DATA / "auto_patch.log"

def _now(): return time.strftime("%Y-%m-%dT%H:%M:%S")

def record_failure(src: str, path: str | None, stderr: str, meta: dict | None = None):
    rec = {"ts": _now(), "src": src, "path": path, "stderr": (stderr or "")[:4000], "meta": meta or {}}
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if BUS:
        BUS.publish("code.error", {"src": src, "path": path, "short": (stderr or "")[:200]})

def scan_and_list(limit: int = 50):
    if not LOG.exists(): return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines()[-limit:]:
        try: out.append(json.loads(line))
        except Exception: pass
    return out
