#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modules/meta_learning.py – FAZA 8: samoocena i uczenie z doświadczeń
Analizuje auto_patch.log i code_registry.json, tworzy ranking skutecznych działań.
"""
from __future__ import annotations
import json, time, hashlib
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

TS = lambda: time.strftime("%Y-%m-%dT%H:%M:%S")

DATA = Path.home() / ".local/share/halbridge"
LOG_PATCH = DATA / "auto_patch.log"
REGISTRY = DATA / "code_registry.json"
SUMMARY = DATA / "meta_summary.json"
def _load_json_lines(p: Path, limit=500):
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8").splitlines()[-limit:]
    out = []
    for L in lines:
        try: out.append(json.loads(L))
        except: pass
    return out

def _load_registry(limit=500):
    if not REGISTRY.exists(): return []
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return data[-limit:] if isinstance(data, list) else []
    except Exception:
        return []

def analyze_failures():
    fails = _load_json_lines(LOG_PATCH)
    by_cmd, by_file = {}, {}
    for f in fails:
        cmd = (f.get("meta") or {}).get("cmd") or f.get("cmd") or "?"
        by_cmd.setdefault(cmd, []).append(f)
        path = f.get("path") or "?"
        by_file.setdefault(path, []).append(f)
    return {"by_cmd": by_cmd, "by_file": by_file}

def analyze_successes():
    regs = _load_registry()
    by_cmd = {}
    for r in regs:
        cmd = (r.get("meta") or {}).get("cmd") or "?"
        if r.get("meta", {}).get("ok") is True:
            by_cmd.setdefault(cmd, []).append(r)
    return by_cmd

def summarize_meta():
    fails = analyze_failures()
    success = analyze_successes()
    stats = []
    cmds = set(list(fails["by_cmd"].keys()) + list(success.keys()))
    for c in cmds:
        f = len(fails["by_cmd"].get(c, []))
        s = len(success.get(c, []))
        eff = s / (s + f) if (s + f) else 0
        stats.append({"cmd": c, "fail": f, "succ": s, "eff": round(eff, 2)})
    stats.sort(key=lambda x: (-x["eff"], -(x["succ"]), x["fail"]))
    SUMMARY.write_text(json.dumps({"ts": TS(), "stats": stats}, indent=2, ensure_ascii=False), encoding="utf-8")
    return stats
def _cli():
    print("📊 Analiza meta-uczenia HALbridge:")
    stats = summarize_meta()
    for s in stats[:10]:
        print(f"→ {s['cmd']:<50}  ✅{s['succ']} ❌{s['fail']}  skuteczność={int(s['eff']*100)}%")
    print(f"\nZapisano podsumowanie: {SUMMARY}")

if __name__ == "__main__":
    _cli()
