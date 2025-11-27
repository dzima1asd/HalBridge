#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import json, re
from collections import Counter

LOG = Path.home() / ".local/share/halbridge/auto_patch.log"

def load_failures(limit=100):
    if not LOG.exists():
        print("Brak pliku auto_patch.log")
        return []
    lines = LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    rec = []
    for l in lines:
        try: rec.append(json.loads(l))
        except: pass
    return rec

def summarize(recs):
    err = Counter(); files = Counter()
    for r in recs:
        msg = r.get("stderr","")
        typ = re.findall(r"([A-Za-z]+Error)", msg)
        err[typ[0] if typ else "Inne"] += 1
        files[r.get("path") or "brak"] += 1
    print(f"\n=== AUTO-HEAL RAPORT ({len(recs)} wpisów) ===")
    print("\nNajczęstsze błędy:")
    for k,v in err.most_common(): print(f"  {k:<20} {v}")
    print("\nNajczęściej zawodzące pliki:")
    for k,v in files.most_common(5): print(f"  {k:<40} {v}")

if __name__ == "__main__":
    data = load_failures()
    if data: summarize(data)
