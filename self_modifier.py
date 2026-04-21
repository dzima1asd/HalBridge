# LEGACY / DISABLED
# ------------------------------------------------------------
# Ten moduł NIE jest częścią aktywnego runtime HALbridge.
# Powstał dla starszej architektury opartej o gpt_chat_v2.py
# i historyczny mechanizm samomodyfikacji kodu.
#
# Status:
# - wyłączony z aktywnego rozwoju
# - nie podłączać do nowego serwera
# - nie używać jako mechanizmu refaktoryzacji ani auto-naprawy
#
# Powód wyłączenia:
# - silne sprzężenie ze starą architekturą v2
# - brak bezpiecznego pipeline'u walidacji zmian
# - ryzyko niekontrolowanych modyfikacji kodu
#
# Jeśli idea wróci w przyszłości, powinna być zrealizowana
# jako kontrolowany system generowania patchy/diffów z
# walidacją, testami i ręcznym zatwierdzeniem operatora.
# ------------------------------------------------------------
import os
import time
import json
from datetime import datetime
from pathlib import Path
from gpt_chat_v2 import GPTChatAPI, Config

# --- GLOBALNA FLAGA KONTROLI ---
AI_SELF_MODIFY = True

# --- KONFIGURACJA I ŚCIEŻKI ---
config = Config()
api = GPTChatAPI(config)
RESTORE_DIR = Path(".restore_points")
LOG_FILE = Path("modification_log.json")
MAX_MODIFICATIONS = 10

# --- PUNKT PRZYWRACANIA ---
def create_restore_point():
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M")
    dest = RESTORE_DIR / ts
    dest.mkdir(parents=True, exist_ok=False)
    files_to_backup = [
        "gpt_chat_v2.py", "halbridge_server.py",
        "device_commands.json", "command_ids.json",
        "session_memory.json"
    ]
    for filename in files_to_backup:
        src = Path(filename)
        if src.exists():
            dest_path = dest / filename
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"\n✅ Punkt przywracania utworzony: {dest}\n")
    return str(dest)

# --- LOG ZMIAN ---
def log_change(prompt: str, change_summary: str, restore_point: str, status: str):
    entry = {
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "change": change_summary,
        "restore_point": restore_point,
        "status": status
    }
    logs = []
    if LOG_FILE.exists():
        try:
            logs = json.loads(LOG_FILE.read_text())
        except:
            pass
    logs.append(entry)
    LOG_FILE.write_text(json.dumps(logs, indent=2, ensure_ascii=False))

# --- PĘTLA SAMOMODYFIKACJI ---
def start_self_modification_loop():
    global AI_SELF_MODIFY
    print("\n⚙️ Tryb samomodyfikacji HALbridge uruchomiony. Komenda zatrzymania: 'Zatrzymaj samomodyfikację'.\n")
    modification_count = 0

    while AI_SELF_MODIFY and modification_count < MAX_MODIFICATIONS:
        restore_point = create_restore_point()
        prompt = "Jak mogę się ulepszyć jako asystent AI terminalowy HalBridge? Wygeneruj konkretną zmianę kodu lub nowy plik."
        ai_response = api.ask_ai(prompt)
        print("\n🤖 AI odpowiada:")
        print(ai_response)

        try:
            # Wykonanie odpowiedzi AI
            api.run_command("echo 'START AI PATCH'")
            if "WYKONAJ:" in ai_response:
                from gpt_chat_v2 import parse_and_execute_ai_response
                parse_and_execute_ai_response(ai_response, config, api.validator, api.executor, None)
            elif "PLIK: zapisz" in ai_response or "plik" in ai_response:
                from gpt_chat_v2 import handle_file_operations
                handle_file_operations(ai_response, api.file_ops, None)
            log_change(prompt, ai_response[:120], restore_point, "success")
        except Exception as e:
            log_change(prompt, str(e), restore_point, "error")

        modification_count += 1
        time.sleep(10)

    print("\n⛔ Zakończono pętlę samomodyfikacji (limit zmian lub polecenie stop).\n")

# --- ZATRZYMANIE PĘTLI ---
def stop_self_modification():
    global AI_SELF_MODIFY
    AI_SELF_MODIFY = False
    print("\n🛑 Samomodyfikacja została zatrzymana przez użytkownika.\n")

# --- TRYB STANDALONE ---
if __name__ == "__main__":
    start_self_modification_loop()
