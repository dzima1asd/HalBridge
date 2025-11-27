#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path
try:
    from modules.bus import BUS
except Exception:
    BUS = None

# Stała ścieżka do zewnętrznego workera Playwright
WORKER_PATH = Path.home() / "HALbridge" / "browser_worker.py"


class BrowserController:
    """Sterowanie przeglądarką przez osobny proces (Playwright worker)."""

    def _run_worker(self, action: str, arg: str) -> str:
        """Uruchamia browser_worker.py z parametrami."""
        if not WORKER_PATH.exists():
            return f"❌ Brak pliku worker: {WORKER_PATH}"

        try:
            result = subprocess.run(
                [sys.executable, str(WORKER_PATH), action, str(arg)],
                capture_output=True,
                text=True,
                timeout=90,
            )
            out = result.stdout.strip()
            err = result.stderr.strip()
            return out or (f"⚠️ {err}" if err else "⚠️ Brak danych z workera")
        except subprocess.TimeoutExpired:
            return "⏰ Worker przekroczył limit czasu (90s)"
        except Exception as e:
            return f"❌ Błąd uruchomienia workera: {e}"

    def open_query(self, text: str) -> str:
        """Otwiera wyszukiwanie lub stronę."""
        return self._run_worker("open", text)

    def click_result(self, index: int) -> str:
        """Kliknięcie w wynik wyszukiwania (numerowane od 0)."""
        return self._run_worker("click", str(index))
