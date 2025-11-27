#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HALbridge BrowserBridge v3
Pełna obsługa przeglądarki Chromium/Playwright dla agenta głosowego:
- otwieranie stron, wyników, obrazów
- przewijanie, cofanie, odświeżanie
- kontrola YouTube (play, next, głośność, fullscreen)
"""

import re
import urllib.parse
from playwright.sync_api import sync_playwright
try:
    from modules.bus import BUS
except Exception:
    BUS = None

class BrowserBridge:
    def __init__(self):
        self._p = None
        self._browser = None
        self._page = None

    def _ensure(self):
        if not self._p:
            self._p = sync_playwright().start()
        if not self._browser:
            self._browser = self._p.chromium.launch(headless=False)
        if not self._page:
            self._page = self._browser.new_page()
            self._page.set_default_timeout(10000)

    def _make_url(self, text: str, mode: str = "search") -> str:
        q = urllib.parse.quote_plus(text.strip())
        if mode == "images":
            return f"https://duckduckgo.com/?q={q}"
        if mode == "youtube":
            return f"https://www.youtube.com/results?search_query={q}"
        return f"https://duckduckgo.com/?q={q}"

    # --- Główne akcje ---
    def open(self, query: str) -> str:
        try:
            self._ensure()
            mode = "search"
            ql = query.lower()
            if any(w in ql for w in ["zdjęcia", "grafika", "obrazy"]):
                mode = "images"
            if "youtube" in ql or "film" in ql or "teledysk" in ql:
                mode = "youtube"
            url = self._make_url(query, mode)
            self._page.goto(url)
            return f"🌍 Otwieram {mode}: {url}"
        except Exception as e:
            return f"❌ Błąd przeglądarki: {e}"

    def list_results(self):
        try:
            self._ensure()
            items = self._page.query_selector_all("a h3")
            return [it.inner_text() for it in items if it.inner_text().strip()]
        except Exception as e:
            return [f"❌ Błąd listy wyników: {e}"]

    def click_result(self, index: int):
        try:
            self._ensure()
            items = self._page.query_selector_all("a h3")
            if index < 0 or index >= len(items):
                return f"❌ Brak wyniku o indeksie {index}"
            items[index].click()
            return f"✅ Kliknięto wynik {index}"
        except Exception as e:
            return f"❌ Błąd kliknięcia: {e}"

    # --- Nawigacja i akcje ---
    def scroll(self, amount: int = 800):
        try:
            self._page.mouse.wheel(0, amount)
            return f"📜 Przewinięto o {amount}px"
        except Exception:
            return "❌ Nie mogę przewinąć."

    def back(self): 
        try:
            self._page.go_back()
            return "⬅️ Cofnięto stronę"
        except Exception:
            return "❌ Nie udało się cofnąć."

    def forward(self): 
        try:
            self._page.go_forward()
            return "➡️ Dalej"
        except Exception:
            return "❌ Nie udało się przejść dalej."

    def refresh(self):
        try:
            self._page.reload()
            return "🔄 Odświeżono"
        except Exception:
            return "❌ Nie mogę odświeżyć."

    # --- Multimedia YouTube ---
    def yt_play_pause(self):
        try:
            self._page.keyboard.press("k")
            return "⏯️ Play/Pause"
        except Exception:
            return "❌ Nie działa play/pause."

    def yt_next(self):
        try:
            self._page.keyboard.press("Shift+n")
            return "⏭️ Następny film"
        except Exception:
            return "❌ Nie działa next."

    def yt_prev(self):
        try:
            self._page.keyboard.press("Shift+p")
            return "⏮️ Poprzedni film"
        except Exception:
            return "❌ Nie działa prev."

    def yt_volume_up(self):
        try:
            self._page.keyboard.press("ArrowUp")
            return "🔊 Głośniej"
        except Exception:
            return "❌ Nie działa głośniej."

    def yt_volume_down(self):
        try:
            self._page.keyboard.press("ArrowDown")
            return "🔉 Ciszej"
        except Exception:
            return "❌ Nie działa ciszej."

    def yt_fullscreen(self):
        try:
            self._page.keyboard.press("f")
            return "⛶ Pełny ekran"
        except Exception:
            return "❌ Nie działa fullscreen."

    def close(self):
        try:
            if self._page: self._page.close()
            if self._browser: self._browser.close()
            return "🧹 Zamknięto przeglądarkę."
        except Exception as e:
            return f"❌ Błąd przy zamykaniu: {e}"
        finally:
            self._page = None
            self._browser = None
            if self._p:
                self._p.stop()
                self._p = None

if __name__ == "__main__":
    b = BrowserBridge()
    while True:
        q = input("Co otworzyć? ").strip()
        if not q or q.lower() in ["exit", "quit"]:
            print(b.close())
            break
        print(b.open(q))
