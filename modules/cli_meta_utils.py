from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone
from modules.runtime_core import SystemInspector
APP_VERSION = "v3.2"
from modules.runtime_core import Config
from dataclasses import dataclass
# Warstwa CLI/meta przeniesiona z gpt_chat_v4.py

def show_help() -> str:
    return (
        "📚 Pomoc:\n"
        "  help                      — ten ekran\n"
        "  jbl on                    — przełącz audio na JBL Charge 4\n"
        "  jbl off                   — wróć na głośnik standardowy\n"
        "  about                     — wersja i model\n"
        "  strict on|off             — włącz/wyłącz STRICT (NLP→bash dla wszystkiego)\n"
        "  model <nazwa>             — ustaw model (np. gpt-4o-mini)\n"
        "  temp <0.0-1.0>            — ustaw temperaturę LLM\n"
        "  max_tokens <int>          — limit tokenów odpowiedzi\n"
        "  tokens                    — skrót kosztów/zużycia\n"
        "  tokens report             — pełny raport (sumy i średnie)\n"
        "  tokens reset              — wyzeruj liczniki (JSON z sumami)\n"
        "  logs tail [N] / grep / export / clear — operacje na logach\n"
        "  project list|new|open|pwd — zarządzanie projektami\n"
        "  read / write              — sandbox plików\n"
        "  ai <prompt>               — rozmowa bez wykonywania\n"
        "  code [plik.py] <prompt>   — generuj→napraw→zapisz→uruchom\n"
        "  vcs init|status|log|diff|commit \"msg\" — git w projekcie\n"
        "  net on|off|allow|deny|list|get — sieć (whitelist)\n"
        "  mem add|list|search|pin|unpin|clear — pamięć CLI\n"
        "  piper status|standard|dark|cyborg — wybór barwy głosu\n"
        "  !<komenda>                — surowy shell\n"
        "  exit                      — wyjście\n"
    )

# =================== CONFIG ===================



def banner(cfg: Config, api: GPTChatAPI):
    print("🌐 GPT TERMINAL v3 — 'exit' aby zakończyć")
    print("📁 read <plik> — odczyt pliku (domyślnie w aktualnym projekcie)")
    print("✏️ write <plik> <treść> — zapis pliku (sandbox)")
    print("🧠 ai <prompt> — rozmowa z LLM (bez wykonania)")
    print("🧩 code [plik.py] <prompt> — wygeneruj kod, preflight, auto-naprawa, uruchom (w projekcie)")
    print("📡 !komenda — wykonanie systemowe (bez NLP)")
    print("📦 project list | new <nazwa> | open <nazwa> | pwd — zarządzanie projektami")
    print("🧠 mem add <tekst> | mem list [N] | mem search <query> | mem pin <id> | mem unpin <id> | mem clear")
    print("🗣️ piper status | piper standard | piper dark | piper cyborg")
    print("🧾 logs tail [N] — ostatnie N linii loga (domyślnie 100)")
    print("💳 tokens — pokaż łączny koszt i tokeny")
    print("🌐 net on|off | allow <dom> | deny <dom> | list | get <URL> [--headers]")
    print("🔧 vcs init | status | log [N] | diff [plik] | commit \"msg\" — kontrola wersji (git)")
    print(f"⚙️ STRICT={'ON' if cfg.STRICT_MODE else 'OFF'} — wszystko inne traktuję jako komendę NLP→bash")
    print(f"📂 Projekt: {api.projects.current_name()}  @  {api.projects.current_path()}")
    print(f"💳 Cennik (USD/1k): {json.dumps(cfg.MODEL_PRICING.get(cfg.OPENAI_MODEL, {}))} | Kurs: {cfg.USD_TO_PLN} PLN/USD")
    print("ℹ️ help — skrót poleceń | about — wersja i model")
    print(f"🛠️ STRICT={ 'ON' if cfg.STRICT_MODE else 'OFF' } | MODEL={cfg.OPENAI_MODEL} | T={cfg.OPENAI_TEMPERATURE} | MAXTOK={cfg.OPENAI_MAX_TOKENS}")
    print("📌 Dostępne modele: gpt-4o | gpt-4o-mini | gpt-4.1 | gpt-4.1-mini | gpt-3.5-turbo")
    print(api.meter.summary())


def render_diag(cfg: Config, api) -> str:
    try:
        sysinfo = SystemInspector.get_system_info()
    except Exception as e:
        sysinfo = {"error": str(e)}

    # tokeny (z pliku totals) + skrót ze `summary()`
    try:
        totals = api.meter._load_totals()  # wewnętrzne, ale przydatne do zbiorczego widoku
    except Exception:
        totals = {"prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0, "cost_pln": 0.0}

    log_path = Path(cfg.APP_LOG_FILE)
    log_exists = log_path.exists()
    log_size = (log_path.stat().st_size if log_exists else 0)

    lines = []
    lines.append("=== DIAG ===")
    lines.append(f"time_utc: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"app_version: {APP_VERSION}")
    lines.append(f"model: {cfg.OPENAI_MODEL}  T={cfg.OPENAI_TEMPERATURE}  MAXTOK={cfg.OPENAI_MAX_TOKENS}")
    lines.append(f"strict_mode: {cfg.STRICT_MODE}  safety_mode: {cfg.SAFETY_MODE}")
    lines.append(f"network: {'ON' if cfg.ENABLE_NETWORK_OPS else 'OFF'}  timeout={cfg.NET_TIMEOUT}s  max={cfg.NET_MAX_BYTES}B")
    lines.append("net_whitelist: " + (", ".join(sorted(cfg.NET_ALLOWED)) if cfg.NET_ALLOWED else "(pusto)"))
    lines.append(f"project: {api.projects.current_name()}  @  {api.projects.current_path()}")
    lines.append("tokens: " + api.meter.summary())
    lines.append(f"tokens_totals: prompt={totals.get('prompt_tokens',0)}, completion={totals.get('completion_tokens',0)}, "
                 f"cost_usd={float(totals.get('cost_usd',0.0)):.4f}, cost_pln={float(totals.get('cost_pln',0.0)):.2f}")
    lines.append(f"log_file: {cfg.APP_LOG_FILE}  exists={log_exists}  size={log_size}B  backups={cfg.LOG_BACKUPS}")

    # Wybrane pola z sysinfo (żeby nie zalać ekranu)
    si_parts = []
    for k in ("system","release","machine","processor","cpu_cores","hostname","python_version","ip_address"):
        if k in sysinfo and sysinfo[k] is not None:
            si_parts.append(f"{k}={sysinfo[k]}")
    lines.append("system_info: " + (", ".join(si_parts) if si_parts else "(brak)"))

    return "\n".join(lines)

# =================== TOKEN METER ===================
