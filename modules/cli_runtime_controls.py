from __future__ import annotations

from modules.cli_meta_utils import render_diag
from modules.voice_state import load_voice_state, save_voice_state


def handle_runtime_controls(line: str, cfg, api) -> tuple[bool, str | None]:
    if line == "strict on":
        cfg.STRICT_MODE = True
        return True, "✅ STRICT: ON"

    if line == "strict off":
        cfg.STRICT_MODE = False
        return True, "✅ STRICT: OFF"

    if line == "smart on":
        state = load_voice_state()
        state["intent_assist_mode"] = "on"
        save_voice_state(state)
        return True, "Smart on - włączono asystę rozumienia"

    if line == "smart off":
        state = load_voice_state()
        state["intent_assist_mode"] = "off"
        save_voice_state(state)
        return True, "Smart off - wyłączono asystę rozumienia"

    if line == "smart auto":
        state = load_voice_state()
        state["intent_assist_mode"] = "auto"
        save_voice_state(state)
        return True, "Smart auto - ustawiono asystę rozumienia na tryb automatyczny"

    if line == "smart status":
        state = load_voice_state()
        mode = str(state.get("intent_assist_mode", "off")).upper()
        provider = str(state.get("intent_assist_provider", "api")).upper()
        return True, f"Smart status - asysta rozumienia: {mode} | provider: {provider}"

    if line.startswith("smart provider "):
        provider = line[len("smart provider "):].strip().lower()
        allowed = {"api", "local", "rules"}
        if provider not in allowed:
            return True, "❌ Dozwolone: smart provider api | local | rules"
        state = load_voice_state()
        state["intent_assist_provider"] = provider
        save_voice_state(state)
        return True, f"Smart provider - ustawiono provider: {provider.upper()}"

    if line == "smart limit status":
        state = load_voice_state()
        limit = int(state.get("intent_assist_api_limit", 100) or 0)
        calls = int(state.get("intent_assist_api_calls_total", 0) or 0)
        if limit > 0:
            left = max(limit - calls, 0)
            return True, f"Smart limit status - API calls: {calls}/{limit} | pozostało: {left}"
        return True, f"Smart limit status - API calls: {calls} | limit: OFF"

    if line.startswith("smart limit set "):
        raw = line[len("smart limit set "):].strip()
        try:
            value = int(raw)
        except Exception:
            return True, "❌ Podaj liczbę całkowitą, np. smart limit set 50"
        if value < 0:
            return True, "❌ Limit nie może być ujemny"
        state = load_voice_state()
        state["intent_assist_api_limit"] = value
        save_voice_state(state)
        if value == 0:
            return True, "Smart limit set - limit API wyłączony"
        return True, f"Smart limit set - ustawiono limit API na: {value}"

    if line == "smart limit reset":
        state = load_voice_state()
        state["intent_assist_api_calls_total"] = 0
        save_voice_state(state)
        limit = int(state.get("intent_assist_api_limit", 100) or 0)
        if limit > 0:
            return True, f"Smart limit reset - wyzerowano licznik API, limit: {limit}"
        return True, "Smart limit reset - wyzerowano licznik API"

    if line == "piper status":
        state = load_voice_state()
        mode = str(state.get("tts_fx_mode", "standard")).lower()
        provider = str(state.get("tts_provider", "piper")).lower()
        return True, f"Piper status - provider: {provider} | głos: {mode}"

    if line in ("piper standard", "glos standard", "głos standard"):
        state = load_voice_state()
        state["tts_fx_mode"] = "standard"
        save_voice_state(state)
        return True, "Piper - ustawiono głos: standard"

    if line in ("piper dark", "glos dark", "głos dark"):
        state = load_voice_state()
        state["tts_fx_mode"] = "dark"
        save_voice_state(state)
        return True, "Piper - ustawiono głos: dark"

    if line in ("piper cyborg", "glos cyborg", "głos cyborg"):
        state = load_voice_state()
        state["tts_fx_mode"] = "cyborg"
        save_voice_state(state)
        return True, "Piper - ustawiono głos: cyborg"

    if line == "diag":
        try:
            api.logger.log(
                "diag.run",
                project=api.projects.current_name(),
                model=cfg.OPENAI_MODEL,
                strict=cfg.STRICT_MODE,
                net=cfg.ENABLE_NETWORK_OPS,
            )
        except Exception:
            pass
        return True, render_diag(cfg, api)

    if line == "net on":
        cfg.ENABLE_NETWORK_OPS = True
        return True, "🌐 Sieć: ON"

    if line == "net off":
        cfg.ENABLE_NETWORK_OPS = False
        return True, "🌐 Sieć: OFF"

    if line.startswith("net allow "):
        dom = line[len("net allow "):].strip().lower()
        if not dom:
            return True, "❌ Podaj domenę"
        if hasattr(cfg, "NET_ALLOWED"):
            if dom not in cfg.NET_ALLOWED:
                cfg.NET_ALLOWED.add(dom)
            return True, f"✅ Dodano do whitelist: {dom}"
        if hasattr(cfg, "ALLOWED_DOMAINS"):
            if dom not in cfg.ALLOWED_DOMAINS:
                cfg.ALLOWED_DOMAINS.append(dom)
            return True, f"✅ Dodano do whitelist: {dom}"
        return True, "❌ Brak konfiguracji whitelist"

    if line.startswith("net deny "):
        dom = line[len("net deny "):].strip().lower()
        if not dom:
            return True, "❌ Podaj domenę"
        if hasattr(cfg, "NET_ALLOWED"):
            if dom in cfg.NET_ALLOWED:
                cfg.NET_ALLOWED.remove(dom)
                return True, f"✅ Usunięto z whitelist: {dom}"
            return True, "❌ Domena nie jest na whitelist"
        if hasattr(cfg, "ALLOWED_DOMAINS"):
            if dom in cfg.ALLOWED_DOMAINS:
                cfg.ALLOWED_DOMAINS = [d for d in cfg.ALLOWED_DOMAINS if d != dom]
                return True, f"✅ Usunięto z whitelist: {dom}"
            return True, "❌ Domena nie jest na whitelist"
        return True, "❌ Brak konfiguracji whitelist"

    if line == "net list":
        if hasattr(cfg, "NET_ALLOWED"):
            wl = sorted(cfg.NET_ALLOWED) or ["(pusto)"]
            status = "ON" if cfg.ENABLE_NETWORK_OPS else "OFF"
            timeout = getattr(cfg, "NET_TIMEOUT", "?")
            maxb = getattr(cfg, "NET_MAX_BYTES", "?")
            return True, "Dozwolone domeny:\n" + "\n".join(f"- {d}" for d in wl) + f"\nStatus: {status} | timeout={timeout}s | max={maxb}B"

        if hasattr(cfg, "ALLOWED_DOMAINS"):
            wl = list(cfg.ALLOWED_DOMAINS) or ["(pusto)"]
            status = "ON" if cfg.ENABLE_NETWORK_OPS else "OFF"
            return True, "Dozwolone domeny:\n" + "\n".join(f"- {d}" for d in wl) + f"\nStatus: {status}"

        return True, "❌ Brak konfiguracji whitelist"

    return False, None
