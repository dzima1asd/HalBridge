#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Moduł: bus.py (FAZA 5 — komunikacja modułowa)
Autor: HalBridge Initiative

Cel:
Umożliwia wymianę komunikatów między modułami HALbridge.
Obsługuje subskrypcje, publikacje i historię zdarzeń.
"""

import json, time, inspect
from collections import defaultdict
from pathlib import Path
from typing import Callable, Any, Dict

LOG_PATH = Path.home() / ".local" / "share" / "halbridge" / "logs" / "bus.log"
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


class MessageBus:
    def __init__(self):
        self._subscribers: Dict[str, list[Callable]] = defaultdict(list)
        self._history: list[dict] = []

    # --- Subskrypcja ----------------------------------------------------------
    def subscribe(self, topic: str, handler: Callable[[dict], None]):
        """Rejestruje funkcję jako odbiorcę wiadomości danego tematu."""
        if not callable(handler):
            raise TypeError("Handler must be callable")
        self._subscribers[topic].append(handler)

    # --- Publikacja -----------------------------------------------------------
    def publish(self, topic: str, payload: Any):
        """Publikuje wiadomość do wszystkich subskrybentów danego tematu."""
        msg = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "topic": topic,
            "payload": payload,
        }
        self._history.append(msg)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")

        for fn in self._subscribers.get(topic, []):
            try:
                fn(payload)
            except Exception as e:
                src = getattr(fn, "__name__", str(fn))
                print(f"[BUS] Błąd w subskrybencie {src}: {e}")

    # --- Historia -------------------------------------------------------------
    def history(self, limit: int = 10):
        """Zwraca ostatnie komunikaty."""
        return self._history[-limit:]


# Singleton globalny
BUS = MessageBus()

# --- Test lokalny ------------------------------------------------------------
if __name__ == "__main__":
    def on_test(msg): print("[HANDLER]", msg)
    BUS.subscribe("demo", on_test)
    BUS.publish("demo", {"msg": "FAZA 5 działa!"})
    print("Historia:", BUS.history(1))
