from __future__ import annotations

def handle_runtime_meta(line: str, api, cfg) -> tuple[bool, str | None]:
    low = (line or "").strip().lower()

    if low.startswith("model "):
        name = line.split(None, 1)[1].strip()
        if not name:
            return True, "⚠ Brak nazwy modelu."
        cfg.OPENAI_MODEL = name
        return True, f"✅ Ustawiono model: {name}"

    if low.startswith("temp "):
        raw = line.split(None, 1)[1].strip()
        try:
            t = float(raw)
        except Exception:
            return True, "❌ Podaj liczbę 0.0–1.0, np. temp 0.2"
        cfg.OPENAI_TEMPERATURE = t
        return True, f"✅ Ustawiono temperaturę: {t}"

    if low.startswith("max_tokens ") or low.startswith("max "):
        raw = line.split(None, 1)[1].strip()
        try:
            mt = int(raw)
            if mt <= 0:
                raise ValueError()
        except Exception:
            return True, "❌ Podaj dodatnią liczbę całkowitą, np. max_tokens 1200"
        cfg.OPENAI_MAX_TOKENS = mt
        return True, f"✅ Ustawiono max_tokens: {mt}"

    return False, None
