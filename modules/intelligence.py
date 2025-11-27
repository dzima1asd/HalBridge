#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moduł: intelligence.py (FAZA 2 — inteligencja i kontekst)
Autor: HalBridge Initiative

Cel:
Analiza promptu, wybór profilu sandboxa i zdefiniowanie celu wykonania (Expected Output).
Łączy świadomość kontekstu z bezpieczeństwem Fazy 1.
"""

import re
import json
from datetime import datetime
try:
    from modules.bus import BUS
except Exception:
    BUS = None

# --- Klasyfikacja typów zadań --------------------------------------------------

def analyze_prompt(prompt: str) -> dict:
    """
    Analizuje treść promptu i określa:
      - typ zadania (data, network, iot, text, viz, system)
      - profil wykonania (headless, iot, analysis)
      - oczekiwany wynik (Expected Output)
    """
    p = prompt.lower()

    # heurystyki typów
    if any(x in p for x in ["csv", "xlsx", "analiza", "wykres", "pandas"]):
        task_type = "data"
    elif any(x in p for x in ["http", "url", "pobierz", "api", "network", "sieć"]):
        task_type = "network"
    elif any(x in p for x in ["mqtt", "shelly", "sensor", "gpio", "iot"]):
        task_type = "iot"
    elif any(x in p for x in ["ascii", "tekst", "string", "markdown"]):
        task_type = "text"
    elif any(x in p for x in ["matplotlib", "plot", "image", "wykres"]):
        task_type = "viz"
    elif any(x in p for x in ["system", "bash", "os.system"]):
        task_type = "system"
    else:
        task_type = "text"

    # profil sandboxa
    profile = choose_profile(task_type)

    # oczekiwany wynik
    expected_output = expected_output_for(task_type)

    return {
        "type": task_type,
        "profile": profile,
        "expected_output": expected_output,
        "ts": datetime.now().isoformat(timespec="seconds")
    }


# --- Dobór profilu --------------------------------------------------------------

def choose_profile(task_type: str) -> str:
    """Mapowanie typu zadania na profil sandboxa"""
    mapping = {
        "data": "analysis",
        "network": "headless",
        "iot": "iot",
        "text": "headless",
        "viz": "headless",
        "system": "headless"
    }
    return mapping.get(task_type, "headless")


# --- Definiowanie celu ----------------------------------------------------------

def expected_output_for(task_type: str) -> str:
    """Opisuje, jakiego rodzaju wynik ma się pojawić"""
    if task_type == "data":
        return "plik CSV lub dane liczbowe"
    if task_type == "iot":
        return "potwierdzenie wykonania akcji lub status urządzenia"
    if task_type == "viz":
        return "ASCII wykres lub zapisany obraz"
    if task_type == "text":
        return "tekst lub przetworzony ciąg znaków"
    if task_type == "system":
        return "log lub wynik polecenia systemowego"
    return "tekst lub dane ogólne"


# --- Walidacja wyniku -----------------------------------------------------------

def validate_result(result: dict) -> bool:
    """
    Sprawdza, czy wynik z sandboxa jest sensowny:
      - brak błędu (returncode == 0)
      - stdout lub plik wyjściowy istnieje
    """
    if not result:
        return False
    if not result.get("ok"):
        return False
    if not result.get("stdout") and not result.get("job"):
        return False
    return True


# --- Auto-fix (placeholder pod FAZĘ 6) -----------------------------------------

def suggest_fix(stderr: str) -> str:
    """
    Analizuje komunikat błędu i generuje sugestię poprawki.
    (prosty mechanizm — pełny auto-fix w Fazie 6)
    """
    if "SyntaxError" in stderr:
        return "Sprawdź składnię: możliwe brakujący dwukropek lub nawias."
    if "ModuleNotFoundError" in stderr:
        return "Brak biblioteki — sprawdź, czy import nie jest zablokowany."
    if "TimeoutExpired" in stderr:
        return "Kod wykonywał się zbyt długo — możliwa pętla nieskończona."
    return "Nieznany błąd — sprawdź logi sandboxa."


# --- Test lokalny ---------------------------------------------------------------

if __name__ == "__main__":
    sample = "Analizuj dane z pliku CSV i narysuj wykres temperatury."
    info = analyze_prompt(sample)
    print("Analiza promptu:")
    print(json.dumps(info, indent=2, ensure_ascii=False))
