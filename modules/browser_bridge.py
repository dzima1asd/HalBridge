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
import sys
import subprocess
import urllib.parse
from pathlib import Path
from playwright.sync_api import sync_playwright
try:
    from modules.bus import BUS
except Exception:
    BUS = None

class BrowserBridge:
    def __init__(self):
        self._p = None
        self._browser = None
        self._context = None
        self._page = None
        self._yt_adguard_enabled = False
        self._yt_worker_proc = None
        self._yt_last_volume_before_mute = 0.5
        self._speaker_auto_started = False
        self._speaker_mqtt_host = "MQTT_HOST"
        self._speaker_topic_prefix = "shellyplus1pm-e465b8940d10"

    def _ensure(self):
        if not self._p:
            self._p = sync_playwright().start()

        if not self._context:
            profile_dir = str(Path.home() / ".hal_browser_profile")
            try:
                self._context = self._p.chromium.launch_persistent_context(
                    profile_dir,
                    headless=False,
                    viewport={"width": 1366, "height": 768},
                    user_agent=(
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run",
                        "--disable-dev-shm-usage",
                        "--remote-debugging-port=9222",
                    ],
                )
            except Exception as e:
                msg = str(e)
                if "ProcessSingleton" in msg or "SingletonLock" in msg or "profile is already in use" in msg:
                    self._browser = self._p.chromium.connect_over_cdp("http://127.0.0.1:9222")
                    contexts = self._browser.contexts
                    if contexts:
                        self._context = contexts[0]
                    else:
                        raise
                else:
                    raise

        if not self._page:
            pages = self._context.pages
            self._page = pages[0] if pages else self._context.new_page()
            self._page.set_default_timeout(10000)

    def _make_url(self, text: str, mode: str = "search") -> str:
        q = urllib.parse.quote_plus(text.strip())
        if mode == "images":
            return f"https://duckduckgo.com/?q={q}"
        if mode == "youtube":
            return f"https://www.youtube.com/results?search_query={q}"
        return f"https://duckduckgo.com/?q={q}"

    def _speaker_topic(self, suffix: str) -> str:
        return f"{self._speaker_topic_prefix}/{suffix}"

    def _speaker_log(self, msg: str):
        try:
            from datetime import datetime
            logp = Path.home() / "HALbridge/logs/browser_speaker.log"
            logp.parent.mkdir(parents=True, exist_ok=True)
            with logp.open("a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().isoformat(timespec='seconds')}] {msg}\n")
        except Exception:
            pass

    def _speaker_mqtt_pub(self, topic: str, payload: str) -> bool:
        try:
            self._speaker_log(f"mqtt_pub topic={topic} payload={payload}")
            res = subprocess.run(
                [
                    "mosquitto_pub",
                    "-h", self._speaker_mqtt_host,
                    "-t", topic,
                    "-m", payload,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self._speaker_log(f"mqtt_pub_result rc={res.returncode}")
            return res.returncode == 0
        except Exception as e:
            self._speaker_log(f"mqtt_pub_error {type(e).__name__}: {e}")
            return False

    def _speaker_get_state(self):
        try:
            self._speaker_mqtt_pub(self._speaker_topic("command/switch:0"), "status_update")
            res = subprocess.run(
                [
                    "mosquitto_sub",
                    "-h", self._speaker_mqtt_host,
                    "-t", self._speaker_topic("status/switch:0"),
                    "-C", "1",
                    "-W", "2",
                ],
                capture_output=True,
                text=True,
                timeout=4,
            )
            if res.returncode != 0:
                return None
            raw = (res.stdout or "").strip()
            if not raw:
                return None
            import json
            data = json.loads(raw)
            if isinstance(data, dict) and "output" in data:
                return bool(data["output"])
            return None
        except Exception:
            return None

    def speaker_on(self):
        ok = self._speaker_mqtt_pub(self._speaker_topic("command/switch:0"), "on")
        return "🔌 Głośnik ON" if ok else "❌ Nie udało się włączyć głośnika."

    def speaker_off(self):
        ok = self._speaker_mqtt_pub(self._speaker_topic("command/switch:0"), "off")
        return "🔌 Głośnik OFF" if ok else "❌ Nie udało się wyłączyć głośnika."

    def _speaker_prepare_for_youtube(self):
        st = self._speaker_get_state()
        self._speaker_log(f"prepare_youtube state={st} auto_started={self._speaker_auto_started}")
        if st is True:
            self._speaker_auto_started = False
            return "already_on"
        ok = self._speaker_mqtt_pub(self._speaker_topic("command/switch:0"), "on")
        if ok:
            self._speaker_auto_started = True
            self._speaker_log("prepare_youtube -> turned_on")
            return "turned_on"
        self._speaker_auto_started = False
        self._speaker_log("prepare_youtube -> error")
        return "error"

    def _speaker_cleanup_after_youtube(self):
        self._speaker_log(f"cleanup_called auto_started={self._speaker_auto_started}")
        if not self._speaker_auto_started:
            return "skip"
        ok = self._speaker_mqtt_pub(self._speaker_topic("command/switch:0"), "off")
        self._speaker_auto_started = False
        return "turned_off" if ok else "error"

    # --- Główne akcje ---
    def open(self, query: str) -> str:
        try:
            self._ensure()
            mode = "search"
            ql = query.lower().strip()
            clean_query = ql

            if any(w in ql for w in ["zdjęcia", "grafika", "obrazy"]):
                mode = "images"
            if "youtube" in ql or "film" in ql or "teledysk" in ql:
                mode = "youtube"

            for prefix in ["otwórz ", "otworz ", "pokaż ", "pokaz ", "znajdź ", "znajdz ", "wyszukaj "]:
                if clean_query.startswith(prefix):
                    clean_query = clean_query[len(prefix):].strip()
                    break

            if mode == "youtube" and clean_query == "youtube":
                url = "https://www.youtube.com"
            else:
                url = self._make_url(clean_query or query, mode)

            self._page.goto(url, wait_until="domcontentloaded")
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
    def _click_youtube_skip_button(self) -> bool:
        try:
            self._ensure()
            selectors = [
                "button.ytp-skip-ad-button",
                "button.ytp-skip-ad-button-modern",
                ".ytp-ad-skip-button-container button.ytp-skip-ad-button",
                ".ytp-ad-skip-button-container button.ytp-skip-ad-button-modern",
                ".ytp-ad-skip-button-slot button.ytp-skip-ad-button",
                ".ytp-ad-skip-button-slot button.ytp-skip-ad-button-modern",
                ".videoAdUiSkipButton button",
                ".videoAdUiSkipButton",
                "[id^='skip-button:']",
            ]

            for sel in selectors:
                try:
                    loc = self._page.locator(sel).first
                    count = loc.count()
                except Exception:
                    continue

                if count < 1:
                    continue

                try:
                    loc.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass

                try:
                    box = loc.bounding_box()
                except Exception:
                    box = None

                if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                    try:
                        x = box["x"] + box["width"] / 2
                        y = box["y"] + box["height"] / 2
                        self._page.mouse.move(x, y)
                        self._page.mouse.down()
                        self._page.mouse.up()
                        try:
                            self._page.wait_for_timeout(350)
                        except Exception:
                            pass
                        return True
                    except Exception:
                        pass

                try:
                    loc.click(timeout=1000, force=True)
                    try:
                        self._page.wait_for_timeout(350)
                    except Exception:
                        pass
                    return True
                except Exception:
                    pass

            return False
        except Exception:
            return False
    def _restore_youtube_audio(self) -> None:
        try:
            self._ensure()
            js = r"""
(() => {
  const v = document.querySelector("video");
  if (v) {
    try { v.muted = false; } catch (e) {}
    try {
      if (v.volume === 0) v.volume = 1.0;
    } catch (e) {}
  }

  const btn = document.querySelector(
    'button[aria-label*="Unmute"], button[aria-label*="Wyłącz wyciszenie"], button[title*="Unmute"], button[title*="Wyłącz wyciszenie"]'
  );
  if (btn) {
    try { btn.click(); } catch (e) {}
  }

  return {
    muted: v ? !!v.muted : null,
    volume: v ? Number(v.volume ?? 0) : null
  };
})();
"""
            for _ in range(4):
                try:
                    res = self._page.evaluate(js)
                except Exception:
                    res = None

                muted = None
                volume = None
                if isinstance(res, dict):
                    muted = res.get("muted")
                    volume = res.get("volume")

                if muted is False and (volume is None or volume > 0):
                    return

                try:
                    self._page.keyboard.press("m")
                    self._page.wait_for_timeout(250)
                except Exception:
                    pass
        except Exception:
            pass

    def _yt_worker_script_path(self) -> Path:
        return Path(__file__).resolve().parent / "browser_yt_autoskip_worker.py"

    def _yt_worker_log_path(self) -> Path:
        return Path("/tmp/browser_yt_autoskip_worker.log")

    def _ensure_yt_worker(self) -> None:
        try:
            if self._yt_worker_proc and self._yt_worker_proc.poll() is None:
                return

            script = self._yt_worker_script_path()
            if not script.exists():
                return

            log_path = self._yt_worker_log_path()
            log_f = open(log_path, "a", encoding="utf-8")

            self._yt_worker_proc = subprocess.Popen(
                [sys.executable, str(script)],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            pass

    def _stop_yt_worker(self) -> None:
        try:
            proc = self._yt_worker_proc
            if not proc:
                return
            if proc.poll() is not None:
                self._yt_worker_proc = None
                return

            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        finally:
            self._yt_worker_proc = None

    def yt_skip_ad(self):
        try:
            self._ensure()
            verify_js = r"""
(() => {
  const adShowing = !!document.querySelector(".ad-showing");
  const adBadge = !!document.querySelector(".ytp-ad-player-overlay, .ytp-ad-preview-container, .ytp-ad-text, .ytp-ad-simple-ad-badge, .video-ads");
  const skipBtn = !!document.querySelector(
    "button.ytp-skip-ad-button, button.ytp-skip-ad-button-modern, .ytp-ad-skip-button-container button.ytp-skip-ad-button, .ytp-ad-skip-button-container button.ytp-skip-ad-button-modern, .ytp-ad-skip-button-slot button.ytp-skip-ad-button, .ytp-ad-skip-button-slot button.ytp-skip-ad-button-modern, .videoAdUiSkipButton button, .videoAdUiSkipButton, [id^='skip-button:']"
  );
  return { adShowing, adBadge, skipBtn };
})();
"""
            state0 = self._page.evaluate(verify_js)
            in_ad = bool(state0.get("adShowing") or state0.get("adBadge") or state0.get("skipBtn"))
            if not in_ad:
                return "ℹ️ Brak reklamy do pominięcia"

            clicked = self._click_youtube_skip_button()
            if not clicked:
                return "ℹ️ Brak przycisku pomiń dla tej reklamy"

            # po kliknięciu dajemy stronie kilka szans na przełączenie stanu
            for _ in range(10):
                try:
                    self._page.wait_for_timeout(400)
                except Exception:
                    pass

                st = self._page.evaluate(verify_js)
                ad_showing = bool(st.get("adShowing"))
                skip_btn = bool(st.get("skipBtn"))

                # sukces uznajemy gdy zniknie aktywny tryb reklamy
                # nawet jeśli jakieś resztki kontenera reklamowego wiszą jeszcze chwilę w DOM
                if not ad_showing and not skip_btn:
                    self._restore_youtube_audio()
                    return "⏭️ Pominięto reklamę"

            return "ℹ️ Klik bbox wykonany, ale reklama nie zniknęła"
        except Exception as e:
            return f"❌ Nie udało się pominąć reklamy: {e}"
    def yt_adguard_on(self):
        try:
            self._ensure()
            js = r"""
(() => {
  if (window.__halYtAdGuard && window.__halYtAdGuard.enabled) {
    return "already_on";
  }

  const prev = window.__halYtAdGuard || {};
  if (prev.timer) { try { clearInterval(prev.timer); } catch (e) {} }
  if (prev.observer) { try { prev.observer.disconnect(); } catch (e) {} }

  const state = {};
  state.enabled = true;
  state.prevMuted = null;
  state.prevVolume = null;
  state.wasInAd = false;
  state.skipFound = 0;
  state.skipClicked = 0;
  state.lastSkipText = "";
  state.lastSkipAt = 0;
  state.lastSkipSig = "";
  state.skipPending = false;
  state.timer = null;
  state.observer = null;

  const isVisible = (el) => {
    try {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    } catch (e) {
      return false;
    }
  };

  const collectText = (el) => {
    try {
      const txt = (el.innerText || "").trim();
      const aria = (el.getAttribute("aria-label") || "").trim();
      return (txt + " " + aria).trim();
    } catch (e) {
      return "";
    }
  };

  const isAdNow = () => {
    try {
      if (document.querySelector(".ad-showing")) return true;

      const selectors = [
        "button.ytp-skip-ad-button",
        "button.ytp-skip-ad-button-modern",
        ".ytp-ad-skip-button-container button.ytp-skip-ad-button",
        ".ytp-ad-skip-button-container button.ytp-skip-ad-button-modern",
        ".ytp-ad-skip-button-slot button.ytp-skip-ad-button",
        ".ytp-ad-skip-button-slot button.ytp-skip-ad-button-modern",
        ".videoAdUiSkipButton button",
        ".videoAdUiSkipButton",
        "[id^='skip-button:']"
      ];

      for (const sel of selectors) {
        let items = [];
        try { items = Array.from(document.querySelectorAll(sel)); } catch (e) {}
        for (const el of items) {
          if (isVisible(el)) return true;
        }
      }

      return false;
    } catch (e) {
      return false;
    }
  };

  const findSkipTarget = () => {
    if (!isAdNow()) return null;

    const selectors = [
      "button.ytp-skip-ad-button",
      "button.ytp-skip-ad-button-modern",
      ".ytp-ad-skip-button-container button.ytp-skip-ad-button",
      ".ytp-ad-skip-button-container button.ytp-skip-ad-button-modern",
      ".ytp-ad-skip-button-slot button.ytp-skip-ad-button",
      ".ytp-ad-skip-button-slot button.ytp-skip-ad-button-modern",
      ".videoAdUiSkipButton button",
      ".videoAdUiSkipButton",
      "[id^='skip-button:']"
    ];

    for (const sel of selectors) {
      let items = [];
      try { items = Array.from(document.querySelectorAll(sel)); } catch (e) {}

      for (const el of items) {
        if (!isVisible(el)) continue;

        const txt = collectText(el).toLowerCase();
        const cls = ((el.className || "").toString()).toLowerCase();
        const aria = ((el.getAttribute("aria-label") || "").toString()).toLowerCase();
        const idv = ((el.id || "").toString()).toLowerCase();

        const looksLikeRealSkip =
          cls.includes("skip-ad") ||
          cls.includes("ad-skip") ||
          idv.startsWith("skip-button:") ||
          aria.includes("skip") ||
          aria.includes("pomiń") ||
          txt.includes("skip ad") ||
          txt.includes("skip ads") ||
          txt.includes("pomiń reklamę") ||
          txt.includes("pomin reklame");

        if (looksLikeRealSkip) return el;
      }
    }

    return null;
  };

  const restoreAudio = () => {
    try {
      const v = document.querySelector("video");
      if (!v) return;

      if (state.prevMuted !== null) {
        v.muted = state.prevMuted;
      } else {
        v.muted = false;
      }

      if (state.prevVolume !== null && !Number.isNaN(state.prevVolume)) {
        v.volume = state.prevVolume;
      } else if (v.volume === 0) {
        v.volume = 1.0;
      }

      if (!v.muted && v.volume === 0) {
        v.volume = 1.0;
      }
    } catch (e) {}
  };

  const handleAdState = () => {
    try {
        if (!state.enabled) return;
      const video = document.querySelector("video");
      const isAd = isAdNow();

      if (isAd) {
        if (!state.wasInAd && video) {
          state.prevMuted = !!video.muted;
          state.prevVolume = Number(video.volume ?? 1);
        }
        state.wasInAd = true;

        if (video) {
          video.muted = true;
          video.volume = 0;
        }

        const target = findSkipTarget();
        if (target) {
          const now = Date.now();
          const sig = [
            collectText(target),
            ((target.className || "").toString()),
            ((target.id || "").toString())
          ].join(" | ").trim();

          state.lastSkipText = collectText(target);

          const sameAsLast = sig && state.lastSkipSig === sig;
          const inCooldown = (now - (state.lastSkipAt || 0)) < 2500;

          if (!(sameAsLast && inCooldown)) {
            state.skipFound += 1;
            state.lastSkipAt = now;
            state.lastSkipSig = sig;
          }
        }
      } else {
        if (state.wasInAd) {
          restoreAudio();
        }
        state.wasInAd = false;
        state.skipPending = false;
      }
    } catch (e) {}
  };

  state.timer = setInterval(handleAdState, 500);

  state.observer = new MutationObserver(() => {
    handleAdState();
  });

  try {
    state.observer.observe(document.documentElement || document.body, {
      childList: true,
      subtree: true,
      attributes: true
    });
  } catch (e) {}

  handleAdState();
  window.__halYtAdGuard = state;
  return "on";
})();
"""
            res = self._page.evaluate(js)
            self._yt_adguard_enabled = True
            self._ensure_yt_worker()
            if res == "already_on":
                return "🛡️ YouTube ad guard już działa"
            return "🛡️ YouTube ad guard: ON"
        except Exception as e:
            return f"❌ Nie udało się włączyć ad guard: {e}"

    def yt_adguard_off(self):


        try:
            self._ensure()
            js = r"""
  (() => {
  const state = window.__halYtAdGuard;
  if (!state || !state.enabled) {
    return "already_off";
  }

  try {
    if (state.timer) clearInterval(state.timer);
  } catch (e) {}

  try {
    if (state.observer) state.observer.disconnect();
  } catch (e) {}

  try {
    const v = document.querySelector("video");
    if (v) {
      if (state.prevMuted !== null) {
        v.muted = state.prevMuted;
      } else {
        v.muted = false;
      }

      if (state.prevVolume !== null && !Number.isNaN(state.prevVolume)) {
        v.volume = state.prevVolume;
      } else if (v.volume === 0) {
        v.volume = 1.0;
      }

      if (!v.muted && v.volume === 0) {
        v.volume = 1.0;
      }
    }
  } catch (e) {}

  state.wasInAd = false;
  state.skipPending = false;
  state.enabled = false;
  state.timer = null;
  state.observer = null;
  window.__halYtAdGuard = state;
  return "off";
})();"""
            res = self._page.evaluate(js)
            self._yt_adguard_enabled = False
            self._stop_yt_worker()
            if res == "already_off":
                return "🛡️ YouTube ad guard już był wyłączony"
            return "🛡️ YouTube ad guard: OFF"
        except Exception as e:
            return f"❌ Nie udało się wyłączyć ad guard: {e}"

    def yt_adguard_status(self):
        try:
            self._ensure()
            js = r"""
(() => {
  const state = window.__halYtAdGuard;
  if (!state || !state.enabled) return {status: "off"};
  return {
    status: state.wasInAd ? "on_ad" : "on",
    skipFound: state.skipFound || 0,
    skipClicked: state.skipClicked || 0,
    lastSkipText: state.lastSkipText || "",
    lastSkipSig: state.lastSkipSig || ""
  };
})();
"""
            res = self._page.evaluate(js)
            if not isinstance(res, dict) or res.get("status") == "off":
                return "🛡️ YouTube ad guard: OFF"

            status = res.get("status", "on")
            found = int(res.get("skipFound", 0) or 0)
            clicked = int(res.get("skipClicked", 0) or 0)
            last_txt = str(res.get("lastSkipText", "") or "")
            last_sig = str(res.get("lastSkipSig", "") or "")

            msg = "🛡️ YouTube ad guard: ON"
            if status == "on_ad":
                msg += " | reklama wykryta"
            msg += f" | skip_found={found} | skip_clicked={clicked}"
            if last_txt:
                msg += f" | last='{last_txt}'"
            if last_sig:
                msg += f" | sig='{last_sig}'"
            return msg
        except Exception:
            return "🛡️ YouTube ad guard: OFF"

    def yt_play_pause(self):
        try:
            self._ensure()
            self._page.keyboard.press("k")
            try:
                self._restore_youtube_audio()
            except Exception:
                pass
            return "⏯️ Play/Pause"
        except Exception:
            return "❌ Nie działa play/pause."

    def yt_next(self):
        try:
            self._ensure()
            self._page.keyboard.press("Shift+n")
            return "⏭️ Następny film"
        except Exception:
            return "❌ Nie działa next."

    def yt_prev(self):
        try:
            self._ensure()
            self._page.keyboard.press("Shift+p")
            return "⏮️ Poprzedni film"
        except Exception:
            return "❌ Nie działa prev."

    def _yt_get_audio_state(self):
        try:
            self._ensure()
            js = '''
(() => {
  const v = document.querySelector("video");
  const url = location.href || "";
  return {
    ok: !!v,
    url: url,
    is_youtube: url.includes("youtube.com"),
    muted: v ? !!v.muted : null,
    volume: v ? Number(v.volume ?? 0) : null
  };
})();
'''
            res = self._page.evaluate(js)
            if isinstance(res, dict):
                return res
        except Exception:
            pass
        return {"ok": False, "is_youtube": False, "muted": None, "volume": None}

    def yt_is_active(self) -> bool:
        st = self._yt_get_audio_state()
        return bool(st.get("ok") and st.get("is_youtube"))

    def yt_is_muted(self) -> bool:
        st = self._yt_get_audio_state()
        return bool(st.get("ok") and st.get("muted"))

    def yt_set_volume(self, percent: int):
        try:
            self._ensure()
            p = int(percent)
            if p < 0:
                p = 0
            if p > 100:
                p = 100

            js = f'''
(() => {{
  const v = document.querySelector("video");
  if (!v) return {{ok:false, reason:"no_video"}};
  try {{ v.muted = false; }} catch (e) {{}}
  try {{ v.volume = {p}/100; }} catch (e) {{}}
  return {{ok:true, muted: !!v.muted, volume: Number(v.volume ?? 0)}};
}})();
'''
            res = self._page.evaluate(js)
            if isinstance(res, dict) and res.get("ok"):
                try:
                    self._yt_last_volume_before_mute = max(0.1, min(1.0, p / 100))
                except Exception:
                    pass
                return f"🔊 Głośność: {p}%"
            return "❌ Nie udało się ustawić głośności."
        except Exception:
            return "❌ Nie udało się ustawić głośności."

    def yt_mute(self):
        try:
            self._ensure()
            st = self._yt_get_audio_state()
            vol = st.get("volume")
            if isinstance(vol, (int, float)) and vol > 0:
                self._yt_last_volume_before_mute = float(vol)

            js = '''
(() => {
  const v = document.querySelector("video");
  if (!v) return {ok:false};
  try { v.muted = true; } catch (e) {}
  return {ok:true};
})();
'''
            res = self._page.evaluate(js)
            if isinstance(res, dict) and res.get("ok"):
                return "🔇 Wyciszono"
            return "❌ Nie udało się wyciszyć."
        except Exception:
            return "❌ Nie udało się wyciszyć."

    def yt_unmute_restore(self):
        try:
            self._ensure()
            prev = self._yt_last_volume_before_mute
            try:
                prev = float(prev)
            except Exception:
                prev = 0.5
            if prev <= 0:
                prev = 0.5
            if prev > 1:
                prev = 1.0

            js = f'''
(() => {{
  const v = document.querySelector("video");
  if (!v) return {{ok:false}};
  try {{ v.muted = false; }} catch (e) {{}}
  try {{
    if (v.volume === 0) v.volume = {prev};
    else v.volume = {prev};
  }} catch (e) {{}}
  return {{ok:true, volume: Number(v.volume ?? 0)}};
}})();
'''
            res = self._page.evaluate(js)
            if isinstance(res, dict) and res.get("ok"):
                return f"🔊 Przywrócono dźwięk ({int(round(prev * 100))}%)"
            return "❌ Nie udało się przywrócić dźwięku."
        except Exception:
            return "❌ Nie udało się przywrócić dźwięku."

    def yt_volume_up(self):
        try:
            self._ensure()
            self._page.keyboard.press("ArrowUp")
            return "🔊 Głośniej"
        except Exception:
            return "❌ Nie działa głośniej."

    def yt_volume_down(self):
        try:
            self._ensure()
            self._page.keyboard.press("ArrowDown")
            return "🔉 Ciszej"
        except Exception:
            return "❌ Nie działa ciszej."

    def yt_fullscreen(self):
        try:
            self._ensure()

            try:
                self._page.keyboard.press("F11")
            except Exception:
                pass

            try:
                self._page.wait_for_timeout(350)
            except Exception:
                pass

            try:
                self._page.keyboard.press("f")
            except Exception:
                pass

            try:
                self._page.wait_for_timeout(200)
            except Exception:
                pass

            return "🖵 Fullscreen toggle"
        except Exception:
            return "❌ Nie działa fullscreen."

    def _dismiss_youtube_consent(self):

        try:
            self._ensure()
            labels = [
                "Odrzuć wszystko",
                "Zaakceptuj wszystko",
                "Reject all",
                "Accept all",
            ]

            selectors = [
                "button",
                'button[aria-label]',
                "ytd-button-renderer button",
                "tp-yt-paper-button",
                "form button",
            ]

            for _ in range(4):
                for sel in selectors:
                    try:
                        items = self._page.query_selector_all(sel)
                    except Exception:
                        items = []

                    for item in items:
                        try:
                            txt = (item.inner_text() or "").strip()
                        except Exception:
                            txt = ""

                        if txt in labels:
                            try:
                                item.click()
                                try:
                                    self._page.wait_for_timeout(1500)
                                except Exception:
                                    pass
                                return "consent_closed"
                            except Exception:
                                pass

                try:
                    self._page.wait_for_timeout(700)
                except Exception:
                    pass
        except Exception:
            pass
        return "consent_not_found"

    def yt_search_and_play(self, query: str):
        try:
            self._ensure()
            q = (query or "").strip()
            if not q:
                return "❌ Podaj czego szukać na YouTube."

            speaker_state = self._speaker_prepare_for_youtube()
            if speaker_state == "turned_on":
                try:
                    self._page.wait_for_timeout(1200)
                except Exception:
                    pass

            url = self._make_url(q, "youtube")
            self._page.goto(url, wait_until="domcontentloaded")

            try:
                self._page.wait_for_timeout(2000)
            except Exception:
                pass

            consent_state = self._dismiss_youtube_consent()

            try:
                self._page.wait_for_timeout(1500)
            except Exception:
                pass

            selectors = [
                "a#video-title",
                "ytd-video-renderer a#video-title",
                "ytm-video-with-context-renderer a#video-title",
            ]

            clicked = False
            for sel in selectors:
                try:
                    items = self._page.query_selector_all(sel)
                    for item in items:
                        try:
                            txt = (item.inner_text() or "").strip()
                        except Exception:
                            txt = ""
                        if item and txt:
                            item.click()
                            clicked = True
                            break
                    if clicked:
                        break
                except Exception:
                    pass

            if clicked:
                adguard_msg = self.yt_adguard_on()
                if consent_state == "consent_closed":
                    return f"▶️ Uruchamiam YouTube: {q} | cookies: zamknięte | {adguard_msg}"
                return f"▶️ Uruchamiam YouTube: {q} | {adguard_msg}"

            return f"🌍 Otwieram youtube: {url}\n❌ Brak wyniku do kliknięcia"
        except Exception as e:
            return f"❌ Błąd YouTube search/play: {e}"

    def close(self, cleanup_speaker: bool = False):
        self._speaker_log(f"close_called cleanup_speaker={cleanup_speaker}")
        try:
            if cleanup_speaker:
                self._speaker_cleanup_after_youtube()
            self._stop_yt_worker()
            if self._page:
                self._page.close()
                self._page = None
            if self._context:
                self._context.close()
                self._context = None
            if self._browser:
                self._browser.close()
                self._browser = None
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
