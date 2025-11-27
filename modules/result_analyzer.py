#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moduł: result_analyzer.py (FAZA 4 — analiza wyników)
Autor: HalBridge Initiative

Cel:
Po uruchomieniu kodu analizuje rezultat i generuje czytelne podsumowanie.
Rozpoznaje: plik, liczby, tekst, ASCII, błąd.
"""

import os, json, re
from pathlib import Path
try:
    from modules.bus import BUS
except Exception:
    BUS = None

LOG_PATH = Path.home() / ".local" / "share" / "halbridge" / "logs" / "code_exec.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

def analyze_result(result: dict, expected_output: str | None = None) -> str:
    """
    Analizuje wynik z sandboxa lub agenta i generuje krótkie podsumowanie.
    """
    if not result:
        return "❌ Brak wyniku."

    if not result.get("ok"):
        err = (result.get("stderr") or "").strip()
        if not err:
            err = result.get("msg", "Nieznany błąd.")
        return f"⚠️ Błąd wykonania:\n{err[:500]}"

    out = (result.get("stdout") or "").strip()
    if not out:
        return "ℹ️ Kod zakończył się bez wyjścia na stdout."

    # Wykryj liczby
    nums = re.findall(r"[-+]?[0-9]*\.?[0-9]+", out)
    if len(nums) > 3:
        return f"📊 Dane liczbowe ({len(nums)} wartości), np.: {', '.join(nums[:5])}..."

    # Wykryj ASCII art (ciągi znaków z #, *, -, _ itd.)
    if re.search(r"[#\*_\-]{5,}", out):
        lines = out.splitlines()
        preview = "\n".join(lines[:15])
        return f"🎨 ASCII output:\n{preview}"

    # Krótki tekstowy wynik
    lines = out.splitlines()
    if len(lines) <= 5:
        return f"💬 Wynik tekstowy: {' '.join(lines)}"
    else:
        preview = "\n".join(lines[:10])
        return f"📄 Dłuższy tekst, pierwsze linie:\n{preview}"

def log_result(result: dict, meta: dict | None = None) -> None:
    """
    Zapisuje wynik do wspólnego logu code_exec.log.
    """
    record = {
        "ts": result.get("ts") or "",
        "ok": result.get("ok"),
        "stdout_len": len(result.get("stdout", "")),
        "stderr_len": len(result.get("stderr", "")),
        "returncode": result.get("returncode"),
        "profile": result.get("profile", "headless"),
        "meta": meta or {},
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

# --- Test lokalny --------------------------------------------------------------

if __name__ == "__main__":
    sample = {
        "ok": True,
        "stdout": "Temperatura: 22.4°C\nWilgotność: 48.7%",
        "stderr": "",
        "returncode": 0,
        "profile": "analysis",
    }
    print(analyze_result(sample, "plik CSV lub dane liczbowe"))
