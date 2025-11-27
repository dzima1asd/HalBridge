# v2
import os
import subprocess
import json
import re
from flask import Flask, request, jsonify, make_response
from gpt_chat_v2 import GPTChatAPI, Config
from self_modifier import start_self_modification_loop, stop_self_modification, AI_SELF_MODIFY
from threading import Thread
from pathlib import Path
import shutil
import traceback
from hardware_bridge import HardwareBridge
bridge = HardwareBridge()
try:
    from modules.bus import BUS
except Exception:
    BUS = None

# === DIAGNOSTYKA SERWERA HALBRIDGE (SELF-HEALING) ===

def diagnose_halbridge():
    print("🩺 Rozpoczynam diagnostykę HalBridge (serwer Flask)...")
    try:
        from gpt_chat_v2 import GPTChatAPI, Config
        import os

        config = Config()
        api = GPTChatAPI(config)

        backup_path = "gpt_chat_v2.py.bak"

        # 1. Inicjalizacja API
        assert api is not None, "Nie udało się utworzyć obiektu GPTChatAPI"

        # 2. Komenda systemowa przez API
        result = api.run_command("echo flasktest")
        assert "flasktest" in result, "Nie działa wykonywanie komend przez API"

        # 3. AI działa lub fallback offline
        ai_resp = api.ask_ai("Jak masz na imię?")
        assert ai_resp, "Brak odpowiedzi od AI (API)"

        # 4. Plik główny jest czytelny
        content = api.read_file("gpt_chat_v2.py")
        assert content and "class" in content, "Błąd odczytu pliku core"

        # 5. (opcjonalnie) Komendy urządzeń — jeśli używasz device_commands.json
        if os.path.isfile("/home/hal/HALbridge/device_commands.json"):
            dc_result = api.device_command("włącz światło")
            assert dc_result is None or isinstance(dc_result, str), "Komendy urządzeń nie działają"

        print("✅ Diagnostyka HalBridge: wszystkie testy zaliczone!")
        # Backup aktualnego kodu core na wszelki wypadek
        shutil.copy("gpt_chat_v2.py", backup_path)
        print("🗂️ Backup core zapisany:", backup_path)

    except Exception as e:
        print("❌ Diagnostyka HalBridge NIEUDANA:", e)
        print(traceback.format_exc())
        backup_path = "gpt_chat_v2.py.bak"
        if os.path.exists(backup_path):
            print("♻️ Przywracam ostatni zdrowy backup!")
            shutil.copy(backup_path, "gpt_chat_v2.py")
            print("🔁 Przywrócono kod z backupu. Uruchom serwer ponownie.")
        else:
            print("🛑 Brak backupu, nie mogę przywrócić systemu!")
        exit(1)

# diagnose_halbridge()

# --- INICJALIZACJA ---
app = Flask(__name__)

# --- CORS HEADERS ---
@app.after_request
def add_cors_headers(response):
    origin = request.headers.get("Origin")
    allowed_origins = ["https://chat.openai.com", "https://chatgpt.com"]
    if origin in allowed_origins:
        response.headers.add("Access-Control-Allow-Origin", origin)
    response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
    response.headers.add("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
    return response

config = Config()
api = GPTChatAPI(config)

# --- AUTORYZACJA ---
API_TOKEN = os.getenv("HALBRIDGE_TOKEN", "bardzo_sekretny_token")

def check_token():
    token = request.headers.get("Authorization", "")
    return token == f"Bearer {API_TOKEN}"

@app.before_request
def auth():
    if request.method != "OPTIONS":
        if not check_token():
            return jsonify(error="Unauthorized"), 401

# --- ENDPOINTY GŁÓWNE ---

from hardware_bridge import HardwareBridge
bridge = HardwareBridge()

@app.route('/run-command', methods=['POST'])
def run_command():
    data = request.get_json(silent=True) or {}
    cmd = (data.get("command") or "").strip()
    if not cmd:
        return jsonify(error="Brak komendy"), 400

    print(f"[🔁 API] Otrzymano komendę: {cmd}")

    # 1) Spróbuj najpierw wykonać komendę sprzętową
    result = None
    try:
        result = bridge.execute(cmd)
        if result:
            print(f"[⚙️ HARDWARE] {result}")
    except Exception as e:
        print(f"[hardware_bridge error] {e}")

    # 2) Jeśli nie rozpoznano komendy sprzętowej → agent
    if not result:
        try:
            result = api.run_command(cmd)
        except Exception as e:
            print(f"[agent error] {e}")
            result = None

    # 3) Ostatecznie, jeśli agent też nie rozpoznał → shell fallback
    if not result:
        try:
            out = subprocess.check_output(
                cmd, shell=True, stderr=subprocess.STDOUT, text=True
            )
            result = out.strip()
        except subprocess.CalledProcessError as e:
            result = (e.output or "").strip() or str(e)

    wrapped = f"@#@{result}@#@" if isinstance(result, str) else f"@#@{str(result)}@#@"
    return jsonify(result=wrapped)

@app.route('/read-file', methods=['POST'])
def read_file():
    path = request.json.get("path")
    if not path:
        return jsonify(error="Brak ścieżki"), 400
    result = api.read_file(path)
    return jsonify(result=result)

@app.route('/write-file', methods=['POST'])
def write_file():
    data = request.json
    path = data.get("path")
    content = data.get("content", "")
    if not path:
        return jsonify(error="Brak ścieżki"), 400
    result = api.write_file(path, content)
    return jsonify(result=result)

@app.route('/history', methods=['GET'])
def history():
    return jsonify(history=api.get_history())

@app.route('/status', methods=['GET'])
def status():
    return jsonify(status="OK", user=os.getenv("USER") or os.getenv("USERNAME"))

# --- ENDPOINTY SAMOMODYFIKACJI ---

@app.route('/start-self-modification', methods=['POST'])
def start_self_mod():
    try:
        t = Thread(target=start_self_modification_loop, daemon=True)
        t.start()
        return jsonify(status="OK", message="Pętla samomodyfikacji uruchomiona."), 200
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/stop-self-modification', methods=['POST'])
def stop_self_mod():
    try:
        stop_self_modification()
        return jsonify(status="OK", message="Samomodyfikacja zatrzymana."), 200
    except Exception as e:
        return jsonify(error=str(e)), 500

# --- ENDPOINTY KONTROLNE ---

@app.route('/self-mod-status', methods=['GET'])
def self_mod_status():
    return jsonify(active=AI_SELF_MODIFY)

@app.route('/list-backups', methods=['GET'])
def list_backups():
    restore_dir = Path(".restore_points")
    if not restore_dir.exists():
        return jsonify(backups=[])
    backups = sorted([p.name for p in restore_dir.iterdir() if p.is_dir()], reverse=True)
    return jsonify(backups=backups)

@app.route('/restore-backup/<backup_name>', methods=['POST'])
def restore_backup(backup_name):
    try:
        source = Path(".restore_points") / backup_name
        if not source.exists() or not source.is_dir():
            return jsonify(error="Backup nie istnieje"), 404

        files_to_restore = [
            "gpt_chat_v2.py", "halbridge_server.py",
            "device_commands.json", "command_ids.json",
            "session_memory.json"
        ]

        for filename in files_to_restore:
            src = source / filename
            if src.exists():
                Path(filename).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

        return jsonify(status="OK", message=f"Przywrócono backup: {backup_name}"), 200
    except Exception as e:
        return jsonify(error=str(e)), 500

@app.route('/mod-log', methods=['GET'])
def mod_log():
    log_path = Path("modification_log.json")
    if not log_path.exists():
        return jsonify(log=[])
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
        return jsonify(log=data)
    except Exception as e:
        return jsonify(error="Nie można odczytać logu", details=str(e)), 500

# --- PRZEKAZYWANIE PROMPTÓW DO AGENTA

class PromptRelay:
    """
    Klasa pośrednicząca: odbiera prompty Plan B przez /run-prompt
    i przekazuje je do lokalnego agenta (gpt_chat_v2.py) pod agent_url.
    Nie wykonuje komend lokalnie – tylko routuje i zwraca odpowiedź.
    """
    def __init__(self, app, agent_url: str = "http://127.0.0.1:8001/ask", token: str = None, timeout: int = 15):
        self.app = app
        self.agent_url = agent_url
        self.token = token
        self.timeout = timeout
        self._register_routes()

    def _post_to_agent(self, payload: dict):
        import requests
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = requests.post(self.agent_url, json=payload, headers=headers, timeout=self.timeout)
        return resp

    def _json_or_text(self, resp):
        try:
            return True, resp.json()
        except Exception:
            text = (resp.text or "").strip()
            # Ujednolicenie formatu odpowiedzi do @#@...@#@, jeśli agent zwrócił zwykły tekst
            if text and not text.startswith("@#@"):
                text = f"@#@{text}@#@"
            return False, {"response": text or "@#@Brak treści odpowiedzi od agenta.@#@"}

    def _register_routes(self):
        from flask import request, jsonify

        @self.app.post("/run-prompt")
        def run_prompt():
            data = request.get_json(silent=True) or {}
            prompt = (data.get("prompt") or "").strip()
            if not prompt:
                return jsonify({"error": "EMPTY_PROMPT", "response": "@#@Nie podano promptu.@#@"}), 400

            try:
                resp = self._post_to_agent({"prompt": prompt})
            except Exception as e:
                return jsonify({
                    "error": "AGENT_UNAVAILABLE",
                    "response": f"@#@Błąd połączenia z agentem: {type(e).__name__}: {e}@#@"
                }), 502

            ok, payload = self._json_or_text(resp)

            # Przekazujemy kod statusu agenta, o ile zwrócił sensowny; w innym wypadku 200
            status = resp.status_code if ok and isinstance(resp.status_code, int) else 200
            return jsonify(payload), status

# --- START SERWERA ---

@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify(ok=Tre), 200

@app.route("/webfetch", methods=["POST"])
def webfetch():
    try:
        data = request.get_json(force=True)
        url = data.get("url", "").strip()
        if not url:
            return jsonify({"error": "missing url"}), 400

        from modules.tools.web_fetch import registry
        result = registry.invoke("web_fetch", {"url": url})

        return jsonify({
            "ok": True,
            "url": url,
            "result": result
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

if __name__ == "__main__":
    print("🚀 Serwer HalBridge rusza z HTTPS na porcie 5000...")
    app.run(host="0.0.0.0", port=5000, ssl_context=('/opt/halbridge/certs/cert.pem', '/opt/halbridge/certs/key.pem'))
