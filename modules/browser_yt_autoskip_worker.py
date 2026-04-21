#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import sys
import time
import urllib.request
from playwright.sync_api import sync_playwright


class YTAutoSkipWorker:
    def __init__(self, cdp_url="http://127.0.0.1:9222", poll_interval=0.35):
        self.cdp_url = cdp_url
        self.poll_interval = poll_interval
        self._pw = None
        self._browser = None

    def _log(self, msg: str):
        print(msg, flush=True)

    def _connect(self):
        if self._pw is None:
            self._pw = sync_playwright().start()
        if self._browser is None:
            self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)

    def _close(self):
        try:
            if self._browser is not None:
                self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None

        try:
            if self._pw is not None:
                self._pw.stop()
        except Exception:
            pass
        finally:
            self._pw = None

    def _all_pages(self):
        self._connect()
        pages = []
        for ctx in self._browser.contexts:
            try:
                pages.extend(ctx.pages)
            except Exception:
                pass
        return pages

    def _find_youtube_page(self):
        pages = self._all_pages()

        preferred = []
        others = []

        for page in pages:
            try:
                url = page.url or ""
            except Exception:
                url = ""

            if "youtube.com/watch" in url:
                preferred.append(page)
            elif "youtube.com" in url:
                others.append(page)

        if preferred:
            return preferred[0]
        if others:
            return others[0]
        return None

    def _page_state(self, page):
        js = r"""
(() => {
  const isVisible = (el) => {
    try {
      if (!el) return false;
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.display !== "none" &&
             style.visibility !== "hidden" &&
             rect.width > 0 &&
             rect.height > 0;
    } catch (e) {
      return false;
    }
  };

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

  let skipReady = false;
  let skipText = "";

  for (const sel of selectors) {
    let items = [];
    try { items = Array.from(document.querySelectorAll(sel)); } catch (e) {}
    for (const el of items) {
      if (!isVisible(el)) continue;
      skipReady = true;
      try {
        skipText = ((el.innerText || "") + " " + (el.getAttribute("aria-label") || "")).trim();
      } catch (e) {}
      break;
    }
    if (skipReady) break;
  }

  const v = document.querySelector("video");
  return {
    url: location.href,
    title: document.title || "",
    adShowing: !!document.querySelector(".ad-showing"),
    skipReady: skipReady,
    skipText: skipText,
    muted: v ? !!v.muted : null,
    volume: v ? Number(v.volume ?? 0) : null
  };
})();
"""
        return page.evaluate(js)


    def _click_continue_watching(self, page) -> bool:
        container_selectors = [
            '[role="dialog"]',
            'tp-yt-paper-dialog',
            'ytd-popup-container',
        ]

        button_selectors = [
            'button',
            '[role="button"]',
            'tp-yt-paper-button',
            'yt-button-shape button',
        ]

        resume_js = """
(() => {
  const v = document.querySelector("video");
  if (!v) return false;
  try { if (v.paused) v.play(); } catch (e) {}
  try { v.muted = false; } catch (e) {}
  try { if (v.volume === 0) v.volume = 1.0; } catch (e) {}
  return true;
})();
"""

        for csel in container_selectors:
            try:
                dialogs = page.locator(csel)
                dcount = dialogs.count()
            except Exception:
                continue

            for i in range(dcount):
                try:
                    dlg = dialogs.nth(i)
                    text = (dlg.inner_text(timeout=500) or "").strip().lower()
                except Exception:
                    continue

                has_pl = ("film został wstrzymany" in text and "chcesz oglądać dalej" in text)
                has_en = ("video paused" in text and "continue watching" in text)

                if not (has_pl or has_en):
                    continue

                for bsel in button_selectors:
                    try:
                        buttons = dlg.locator(bsel)
                        bcount = buttons.count()
                    except Exception:
                        continue

                    for j in range(bcount):
                        try:
                            btn = buttons.nth(j)
                            label = (btn.inner_text(timeout=300) or "").strip().lower()
                        except Exception:
                            label = ""

                        if label not in ("tak", "yes"):
                            continue

                        try:
                            box = btn.bounding_box()
                        except Exception:
                            box = None

                        if box and box.get("width", 0) > 0 and box.get("height", 0) > 0:
                            try:
                                x = box["x"] + box["width"] / 2
                                y = box["y"] + box["height"] / 2
                                page.mouse.move(x, y)
                                page.mouse.down()
                                page.mouse.up()
                                page.wait_for_timeout(300)
                                try:
                                    page.evaluate(resume_js)
                                except Exception:
                                    pass
                                return True
                            except Exception:
                                pass

                        try:
                            btn.click(timeout=1000, force=True)
                            page.wait_for_timeout(300)
                            try:
                                page.evaluate(resume_js)
                            except Exception:
                                pass
                            return True
                        except Exception:
                            pass

        return False

    def _click_skip_button(self, page) -> bool:
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
                loc = page.locator(sel).first
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
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.up()
                    page.wait_for_timeout(350)
                    return True
                except Exception:
                    pass

            try:
                loc.click(timeout=1000, force=True)
                page.wait_for_timeout(350)
                return True
            except Exception:
                pass

        return False

    def _restore_audio(self, page):
        js = r"""
(() => {
  const v = document.querySelector("video");
  if (v) {
    try { v.muted = false; } catch (e) {}
    try { if (v.volume === 0) v.volume = 1.0; } catch (e) {}
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
        try:
            page.evaluate(js)
        except Exception:
            pass

    def run_once(self) -> bool:
        page = self._find_youtube_page()
        if page is None:
            return False

        try:
            if self._click_continue_watching(page):
                try:
                    self._restore_audio(page)
                except Exception:
                    pass
                self._log("[autoskip] continue-watching clicked")
                return True
        except Exception as e:
            self._log(f"[autoskip] continue-watching error: {e}")

        try:
            st = self._page_state(page)
        except Exception as e:
            self._log(f"[autoskip] state error: {e}")
            return False

        ad_showing = bool(st.get("adShowing"))
        skip_ready = bool(st.get("skipReady"))

        if not ad_showing or not skip_ready:
            return False

        clicked = self._click_skip_button(page)
        if not clicked:
            return False

        try:
            page.wait_for_timeout(700)
        except Exception:
            pass

        self._restore_audio(page)

        try:
            st2 = self._page_state(page)
        except Exception:
            st2 = {}

        self._log(
            "[autoskip] clicked"
            + f" | ad={bool(st2.get('adShowing'))}"
            + f" | skip={bool(st2.get('skipReady'))}"
            + f" | title={str(st2.get('title', ''))[:80]}"
        )
        return True

    def run_forever(self):

        self._log(f"[autoskip] connecting to {self.cdp_url}")
        self._connect()
        self._log("[autoskip] started")

        try:
            while True:
                try:
                    self.run_once()
                except KeyboardInterrupt:
                    raise
                except Exception as e:
                    self._log(f"[autoskip] loop error: {e}")
                    try:
                        self._close()
                    except Exception:
                        pass
                    time.sleep(1.0)
                    try:
                        self._connect()
                    except Exception as e2:
                        self._log(f"[autoskip] reconnect error: {e2}")
                        time.sleep(2.0)
                time.sleep(self.poll_interval)
        finally:
            self._close()
            self._log("[autoskip] stopped")


def main():
    cdp_url = "http://127.0.0.1:9222"
    if len(sys.argv) > 1 and sys.argv[1].strip():
        cdp_url = sys.argv[1].strip()

    worker = YTAutoSkipWorker(cdp_url=cdp_url)
    worker.run_forever()


if __name__ == "__main__":
    main()
