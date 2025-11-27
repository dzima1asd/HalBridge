#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HALbridge Hardware Bridge — pełna wersja
z LIVE Shelly, pamięcią kontekstu, aliasami,
fuzzy, toggle, powtórz, światło bez numeru
i solidnym stanem urządzeń.
"""

from __future__ import annotations
import json
import re
import difflib
import subprocess
from pathlib import Path
from typing import Optional, Dict, List, Tuple

try:
    from modules.bus import BUS
except Exception:
    BUS = None

try:
    import requests
except Exception:
    requests = None

# ==========================================
# Ścieżki
# ==========================================

DEFAULT_CONFIG = "/home/hal/HALbridge/device_commands.json"

STATE_DIR = Path("~/.local/share/halbridge").expanduser()
STATE_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH = STATE_DIR / "hw_context.json"

# ==========================================
# Mapowanie na Shelly (LIVE)
# ==========================================

_SHELLY_LIGHT_MAP_RAW = {
    "światło 1": {"ip": "192.168.100.12", "id": 0},
    "światło 2": {"ip": "192.168.100.12", "id": 1},
}
SHELLY_LIGHT_MAP = {re.sub(r"\s+", " ", k.lower()): v for k, v in _SHELLY_LIGHT_MAP_RAW.items()}


# ==========================================
# UTIL
# ==========================================

def _slug(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _split_targets(text: str) -> List[str]:
    parts = re.split(r"\s*(?:,| i | oraz )\s*", text, flags=re.IGNORECASE)
    return [p.strip() for p in parts if p.strip()]


# ==========================================
#  HARDWARE BRIDGE
# ==========================================

class HardwareBridge:

    # ---------------------------------------------------
    # INIT
    # ---------------------------------------------------

    def __init__(self, config_path: str = DEFAULT_CONFIG):
        self.config_path = Path(config_path)
        self.commands: Dict[str, Dict[str, str]] = self._load_commands()
        self.aliases: Dict[str, List[str] | str] = self._default_aliases()

        # kontekst
        self.last_action: Optional[str] = None     # "włącz" / "wyłącz"
        self.last_targets: List[str] = []

        # stan urządzeń
        self.state: Dict[str, str] = {k: "unknown" for k in self.commands.keys()}
        self.state_source: Dict[str, str] = {k: "memory" for k in self.commands.keys()}

        self._load_context()

    # ---------------------------------------------------
    # I/O
    # ---------------------------------------------------

    def _load_commands(self) -> Dict[str, Dict[str, str]]:
        if not self.config_path.exists():
            print(f"⚠️ Brak pliku {self.config_path}")
            return {}
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {_slug(k): v for k, v in (data or {}).items()}
        except Exception as e:
            print(f"❌ Błąd ładowania device_commands.json: {e}")
            return {}

    def reload(self):
        self.commands = self._load_commands()
        for k in self.commands.keys():
            self.state.setdefault(k, "unknown")
            self.state_source.setdefault(k, "memory")

    def _save_context(self):
        try:
            with open(STATE_PATH, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "last_action": self.last_action,
                        "last_targets": self.last_targets,
                        "state": self.state,
                        "state_source": self.state_source,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"⚠️ Nie zapisano kontekstu: {e}")

    def _load_context(self):
        try:
            if STATE_PATH.exists():
                with open(STATE_PATH, "r", encoding="utf-8") as fh:
                    obj = json.load(fh)

                self.last_action = obj.get("last_action")
                self.last_targets = obj.get("last_targets", []) or []

                loaded_state = obj.get("state", {}) or {}
                loaded_source = obj.get("state_source", {}) or {}

                for k in self.commands.keys():
                    self.state[k] = loaded_state.get(k, "unknown")
                    self.state_source[k] = loaded_source.get(k, "memory")
        except Exception as e:
            print(f"⚠️ Nie odczytano kontekstu: {e}")

    def _reload_state(self):
        """Soft-refresh – wciąga zmiany z hw_context.json."""
        try:
            if not STATE_PATH.exists():
                return
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                obj = json.load(fh)

            st = obj.get("state", {}) or {}
            src = obj.get("state_source", {}) or {}

            for k in self.commands.keys():
                self.state[k] = st.get(k, self.state.get(k, "unknown"))
                self.state_source[k] = src.get(k, self.state_source.get(k, "memory"))

        except Exception:
            return

    # ---------------------------------------------------
    # ALIASY
    # ---------------------------------------------------

    def _default_aliases(self) -> Dict[str, List[str] | str]:
        def all_matching(substr: str) -> List[str]:
            key = _slug(substr)
            return [k for k in self.commands.keys() if key in k]

        base: Dict[str, List[str] | str] = {
            # światła
            "pierwsze światło": "światło 1",
            "drugie światło": "światło 2",
            "pierwsza lampa": "światło 1",
            "druga lampa": "światło 2",
            "światło numer jeden": "światło 1",
            "światło numer dwa": "światło 2",

            # diody
            "zielone": "zielona dioda",
            "czerwone": "czerwona dioda",
            "dioda zielona": "zielona dioda",
            "dioda czerwona": "czerwona dioda",
        }

        # dynamiczne aliasy zbiorów
        base["wszystkie światła"] = all_matching("światło")
        base["oba światła"] = all_matching("światło")
        base["lampy"] = all_matching("światło")
        base["światła"] = all_matching("światło")
        base["oba"] = all_matching("światło")

        base["wszystkie diody"] = all_matching("dioda")
        base["diody"] = all_matching("dioda")

        # względne
        if "światło 1" in self.commands:
            base.setdefault("pierwsze", "światło 1")
        if "światło 2" in self.commands:
            base.setdefault("drugie", "światło 2")

        normalized = {}
        for k, v in base.items():
            normalized[_slug(k)] = v
        return normalized

    # ---------------------------------------------------
    # AKCJA
    # ---------------------------------------------------

    def _parse_action(self, text: str) -> Optional[str]:
        t = _slug(text)

        # powtórz
        if re.search(r"\b(powtórz|to samo|ponownie|jeszcze raz)\b", t):
            return self.last_action or None

        # toggle
        if re.search(r"\b(odwrotnie|na odwrót|przełącz|toggle)\b", t):
            if self.last_action == "włącz":
                return "wyłącz"
            if self.last_action == "wyłącz":
                return "włącz"
            return None

        on_words = ["włącz", "wlacz", "zaświeć", "zaswiec", "uruchom", "odpal"]
        off_words = ["wyłącz", "wylacz", "zgaś", "zgas", "zatrzymaj", "wyłączyć"]

        if any(w in t for w in on_words):
            return "włącz"
        if any(w in t for w in off_words):
            return "wyłącz"

        return None

    def _strip_action_words(self, text: str) -> str:
        t = " " + _slug(text) + " "
        t = re.sub(r"\b(włącz|wlacz|zaświeć|zaswiec|uruchom|odpal)\b", " ", t)
        t = re.sub(r"\b(wyłącz|wylacz|zgaś|zgas|zatrzymaj|wyłączyć)\b", " ", t)
        t = re.sub(r"\b(powtórz|to samo|ponownie|jeszcze raz|odwrotnie|na odwrót|przełącz|toggle)\b", " ", t)
        return re.sub(r"\s+", " ", t).strip()

    # ---------------------------------------------------
    # TARGETY
    # ---------------------------------------------------

    def _resolve_single(self, name: str) -> List[str]:
        key = _slug(name)

        if key in self.aliases:
            v = self.aliases[key]
            if isinstance(v, list):
                return [_slug(x) for x in v if _slug(x) in self.commands]
            s = _slug(v)
            return [s] if s in self.commands else []

        if key in self.commands:
            return [key]

        contains = [dev for dev in self.commands if key in dev]
        if contains:
            return contains

        match = difflib.get_close_matches(key, list(self.commands.keys()), n=1, cutoff=0.72)
        if match:
            return [match[0]]

        if key in ("pierwsze", "pierwszy") and self.last_targets:
            return [self.last_targets[0]]

        if key in ("drugie", "drugi") and len(self.last_targets) >= 2:
            return [self.last_targets[1]]

        return []

    def _resolve_targets(self, text: str) -> List[str]:
        parts = _split_targets(text)
        targets: List[str] = []
        for p in parts:
            targets.extend(self._resolve_single(p))

        if not targets and re.search(r"\b(to samo|powtórz|ponownie|jeszcze raz)\b", _slug(text)):
            return list(self.last_targets)

        seen = set()
        uniq = []
        for t in targets:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq

    # ---------------------------------------------------
    # LIVE Shelly
    # ---------------------------------------------------

    def _refresh_live_state_for_device(self, dev: str) -> None:
        if not requests:
            return

        info = SHELLY_LIGHT_MAP.get(dev)
        if not info:
            return

        ip = info.get("ip")
        chan_id = info.get("id")
        if not ip:
            return

        url = f"http://{ip}/rpc/Switch.GetStatus?id={chan_id}"
        try:
            r = requests.get(url, timeout=1.5)
            if r.status_code != 200:
                return
            data = r.json()
            out = data.get("output")
            if isinstance(out, bool):
                self.state[dev] = "on" if out else "off"
                self.state_source[dev] = "live"
        except Exception:
            return

    def refresh_live_state(self) -> None:
        for dev in list(self.state.keys()):
            if dev in SHELLY_LIGHT_MAP:
                self._refresh_live_state_for_device(dev)

    # ---------------------------------------------------
    # Logika światła bez numeru
    # ---------------------------------------------------

    def resolve_light_without_number(self, raw_text: str) -> Optional[str]:
        t = _slug(raw_text)

        action = self._parse_action(raw_text)
        if not action:
            return None

        if "światło" not in t:
            return None

        if re.search(r"\b1\b|\b2\b", t):
            return None

        on_list = [dev for dev, st in self.state.items() if st == "on"]
        off_list = [dev for dev, st in self.state.items() if st == "off"]

        if action == "wyłącz" and len(on_list) == 1:
            return f"{action} {on_list[0]}"

        if action == "włącz" and len(off_list) == 1:
            return f"{action} {off_list[0]}"

        print(f"🤔 Które światło mam {action}? (1/2)")
        print("(czekam 10 sekund...)")

        import select, sys
        r, _, _ = select.select([sys.stdin], [], [], 10)

        if r:
            ans = sys.stdin.readline().strip().lower()

            if ans.startswith("1"):
                return f"{action} światło 1"
            if ans.startswith("2"):
                return f"{action} światło 2"
            if any(x in ans for x in ("oba", "1 i 2", "1,2", "1 2")):
                return f"{action} światło 1 i światło 2"

            print(f"⚠️ Nie rozumiem, {action} oba.")
            return f"{action} światło 1 i światło 2"

        print(f"⌛ Czas minął — {action} oba światła.")
        return f"{action} światło 1 i światło 2"

    # ---------------------------------------------------
    # WYKONANIE
    # ---------------------------------------------------

    def _run(self, cmd: str):
        try:
            subprocess.run(cmd, shell=True, check=False, timeout=10)
        except Exception as e:
            print(f"❌ Błąd wykonania komendy: {e}")

    def _exec_for(self, action: str, targets: List[str]) -> Tuple[List[str], List[str]]:
        ok, missing = [], []
        for dev in targets:
            entry = self.commands.get(dev) or {}
            cmd = entry.get(action)

            if not cmd:
                missing.append(dev)
                continue

            print(f"➡️ {action.upper()} → {dev}")
            self._run(cmd)
            ok.append(dev)

            if action == "włącz":
                self.state[dev] = "on"
            elif action == "wyłącz":
                self.state[dev] = "off"

            self.state_source[dev] = self.state_source.get(dev, "memory") or "memory"

        return ok, missing

    # ---------------------------------------------------
    # PUBLIC API
    # ---------------------------------------------------

    def execute(self, text: str) -> Optional[str]:
        self._reload_state()

        if not text or not self.commands:
            return None

        slug = _slug(text)

        if slug in ("światła status", "status świateł", "światła stan", "status światła"):
            lines = []
            for dev in sorted(self.state.keys()):
                if "światło" in dev:
                    st = self.state.get(dev, "unknown")
                    src = self.state_source.get(dev, "memory")
                    lines.append(f"{dev}: {st} ({src})")
            return " | ".join(lines) if lines else "brak znanych świateł"

        raw = text

        self._reload_state()
        self.refresh_live_state()

        modified = self.resolve_light_without_number(raw)
        if modified:
            raw = modified

        action = self._parse_action(raw)
        targets_text = self._strip_action_words(raw)
        targets = self._resolve_targets(targets_text)

        if not action and not targets:
            return None

        if not action:
            return None

        if not targets:
            return None

        ok, missing = self._exec_for(action, targets)

        if ok:
            self.last_action = action
            self.last_targets = ok
            self._save_context()

        msg = []
        if ok:
            msg.append(f"✅ {action} wykonano dla: {', '.join(ok)}")
        if missing:
            msg.append(f"⚠️ Brak komendy '{action}' dla: {', '.join(missing)}")
        return " | ".join(msg) if msg else None


# ==========================================
#  TEST LOKALNY
# ==========================================

if __name__ == "__main__":
    hb = HardwareBridge()
    print("HALbridge Hardware Bridge — test (pusta linia kończy)")
    try:
        while True:
            t = input("> ").strip()
            if not t:
                break
            print(hb.execute(t) or "∅ brak akcji/targetów")
    except KeyboardInterrupt:
        print("\n∎")
