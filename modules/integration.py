#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
modules/integration.py — FAZA 6 „pełne intencje”
- Publikuje intencje z intelligence na BUS.
- Trasuje prośby do modułów: hardware_bridge, browser_controller, gmail_bridge.
- Zero twardych zależności (każdy moduł jest opcjonalny).
- Obsługuje NATYWNIE IOT przez hardware_bridge, bez LLM i bez tokenów.
"""

from __future__ import annotations
from typing import Optional, Dict

try:
    from modules.bus import BUS
except Exception:
    BUS = None


def _pub(topic: str, payload: Dict):
    if BUS:
        BUS.publish(topic, payload)


# ===============================================================
# IOT DISPATCHER (kluczowa różnica między FAZA 5 a FAZA 6)
# ===============================================================

def _dispatch_iot(context: Dict):
    """
    Obsługa IOT *bezpośrednio* przez hardware_bridge.
    Pozwala na:
      - zero-tokenowe działanie (słownik urządzeń)
      - rozumienie języka naturalnego przez hardware_bridge
    """
    text = context.get("code") or ""
    if not text.strip():
        return

    try:
        from hardware_bridge import HardwareBridge
    except Exception:
        return

    try:
        hb = HardwareBridge()
        hb.reload()
        result = hb.execute(text)
        if result:
            _pub("iot.result", {"result": result, "context": context})
    except Exception:
        pass


# ===============================================================
# GŁÓWNY ROUTER INTENCJI
# ===============================================================

def route(meta: Dict, context: Dict):
    """
    meta: wynik intelligence.analyze_prompt()
    context: {"code": str, "source": "snippet"|"file", "path": Optional[str]}
    """

    # 1) Publikacja intencji (bez kodu, czysto meta)
    _pub("code.intent", {
        "meta": meta,
        "context": {k: v for k, v in context.items() if k != "code"}
    })

    task = (meta or {}).get("type") or "text"

    # ===========================================================
    # INTENT → IOT
    # ===========================================================
    if task == "iot":
        # event systemowy
        _pub("iot.request", {"action": "execute", "context": context})

        # NATYWNE wykonanie na sprzęcie
        _dispatch_iot(context)
        return

    # ===========================================================
    # INTENT → INTERNET / WYKRESY / DANE
    # ===========================================================
    if task in ("network", "viz", "text", "data"):
        _pub("browser.request", {"action": "fetch-or-render", "context": context})
        try:
            from modules import browser_controller
            if hasattr(browser_controller, "ingest"):
                browser_controller.ingest({"type": task, "context": context})
        except Exception:
            pass
        return

    # ===========================================================
    # INTENT → SYSTEM
    # ===========================================================
    if task == "system":
        _pub("system.request", {"action": "execute", "context": context})
        return

    # ===========================================================
    # INTENT → MAIL (heurystyka)
    # ===========================================================
    text = (context.get("code") or "").lower()
    if any(x in text for x in ("mail", "gmail", "inbox", "email", "poczta")):
        _pub("gmail.request", {"action": "query", "context": context})
        try:
            from modules.gmail_bridge import gmail_bridge
            if hasattr(gmail_bridge, "ingest"):
                gmail_bridge.ingest({"type": "mail", "context": context})
        except Exception:
            pass
        return
