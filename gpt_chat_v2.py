# gpt_chat_v2.py 

import os
import re
import shlex
import subprocess
import platform
import json
import hashlib
import requests
import stat
import time
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from pathlib import Path
import psutil
import getpass
import difflib
import shutil
import traceback
import importlib.util
import sys
import ast

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # do testów offline

import openai  # jeśli gdzieś dalej używasz

# === DIAGNOSTYKA SYSTEMU & SELF-HEALING ===
def diagnose_and_heal():
    print("🩺 Rozpoczynam diagnostykę systemu HalBridge...")
    # Uwaga: import własnego modułu w tej samej nazwie pliku działa,
    # bo funkcja jest wołana z __main__ po załadowaniu kodu.
    from gpt_chat_v2 import GPTChatAPI, Config

    config = Config()
    api = GPTChatAPI(config)
    backup_path = "gpt_chat_v2.py.bak"
    test_file = "diagnose_test.txt"

    try:
        # 1. Inicjalizacja API
        assert api is not None, "Nie udało się utworzyć obiektu GPTChatAPI"

        # 2. Komenda systemowa
        result = api.run_command("echo test")
        assert "test" in result, "Nie działa wykonywanie komend systemowych"

        # 3. Walidacja bezpieczeństwa
        blocked = api.run_command("rm -rf /")
        assert "Blokada" in blocked or "blokada" in blocked, "Walidator NIE blokuje niebezpiecznych komend!"

        # 4. Odczyt pliku
        content = api.read_file("gpt_chat_v2.py")
        assert content and "class" in content, "Błąd odczytu głównego pliku"

        # 5. Zapis/odczyt pliku
        api.write_file(test_file, "sprawdzam")
        test_read = api.read_file(test_file)
        assert "sprawdzam" in test_read, "Błąd zapisu/odczytu testowego pliku"
        os.remove(test_file)

        # 6. Historia
        hist = api.get_history()
        assert isinstance(hist, list), "Historia nie działa!"

        # 7. Komendy urządzeń (jeśli plik istnieje)
        if os.path.isfile("/home/hal/HALbridge/device_commands.json"):
            dc_result = api.device_command("testowa komenda sprzętowa")
            assert dc_result is None or isinstance(dc_result, str), "Komendy urządzeń nie działają"

        print("✅ Diagnostyka: wszystkie kluczowe funkcje działają!")

        # 8. Backup po sukcesie
        shutil.copy("gpt_chat_v2.py", backup_path)
        print("🗂️ Aktualny backup zapisany:", backup_path)
        return True

    except Exception as e:
        print("❌ Diagnostyka NIEUDANA:", e)
        print(traceback.format_exc())
        if os.path.exists(backup_path):
            print("♻️ Przywracam ostatni zdrowy backup!")
            shutil.copy(backup_path, "gpt_chat_v2.py")
            print("🔁 Przywrócono kod z backupu. Uruchom ponownie system.")
        else:
            print("🛑 Brak backupu, nie mogę przywrócić systemu!")
        exit(1)

# === Konfiguracja ===
class Config:
    def __init__(self):
        self.LOG_FILE = "command_log.json"
        self.SAFETY_MODE = True
        self.MAX_HISTORY = 50
        self.SYSTEM_INFO = True
        self.ENABLE_FILE_OPS = True
        self.ENABLE_NETWORK_OPS = False
        self.ALLOWED_DIRS = [str(Path.home())]
        self.BLACKLISTED_DIRS = ["/etc", "/bin", "/sbin", "/usr"]
        self.MEMORY_FILE = "session_memory.json"
        self.OPENAI_MODEL = "gpt-4"
        self.COMMAND_PREFIX = "!"
        self.AUTO_UPDATE_URL = "https://raw.githubusercontent.com/dzima1asd/Python-projekty/main/gpt_chat.py"
        self.AUTO_UPDATE_HASH_URL = self.AUTO_UPDATE_URL + ".sha256"

# === System Inspector ===
class SystemInspector:
    @staticmethod
    def get_system_info() -> Dict:
        try:
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            return {
                "system": platform.system(),
                "release": platform.release(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "cpu_cores": os.cpu_count(),
                "memory": {"total": mem.total, "available": mem.available, "percent": mem.percent},
                "disk_usage": {"total": disk.total, "used": disk.used, "free": disk.free, "percent": disk.percent},
                "current_user": getpass.getuser(),
                "hostname": platform.node(),
                "ip_address": SystemInspector.get_ip_address(),
                "environment": {k: v for k, v in os.environ.items() if not any(s in k.lower() for s in ["key", "pass", "token"])},
                "python_version": platform.python_version(),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_ip_address() -> str:
        try:
            return requests.get('https://api.ipify.org', timeout=3).text
        except:
            try:
                return requests.get('https://ifconfig.me', timeout=3).text
            except:
                return "127.0.0.1"

# === Session Memory ===
class SessionMemory:
    def __init__(self, config: Config):
        self.config = config
        self.memory_file = self.config.MEMORY_FILE
        self.data: Dict[str, str] = {}
        self.load()

    def load(self):
        if os.path.isfile(self.memory_file):
            try:
                with open(self.memory_file, "r") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}

    def save(self):
        try:
            with open(self.memory_file, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"Błąd zapisu pamięci sesji: {e}")

    def set(self, key: str, value: str):
        self.data[key] = value
        self.save()

    def get(self, key: str) -> Optional[str]:
        return self.data.get(key)

    def clear(self):
        self.data = {}
        self.save()

# === SAMOUCZĄCA SIĘ PAMIĘĆ KOMEND GPT ===

class CommandMemoryHandler:
    def __init__(self, filepath="learned_commands.json"):
        self.filepath = filepath
        if not os.path.exists(filepath):
            with open(filepath, "w") as f:
                json.dump({}, f)

    def load(self):
        with open(self.filepath, "r") as f:
            return json.load(f)

    def save(self, data):
        with open(self.filepath, "w") as f:
            json.dump(data, f, indent=2)

    def find_command(self, phrase, action):
        data = self.load()
        return data.get(phrase, {}).get(action)

    def add_command(self, phrase, action, command):
        data = self.load()
        if phrase not in data:
            data[phrase] = {}
        data[phrase][action] = command
        self.save(data)

def ask_gpt_for_command(user_input, model="gpt-4"):
    prompt = (
        f"Zinterpretuj polecenie: „{user_input}” jako jedną konkretną "
        f"komendę bash, którą można wykonać w terminalu linuksowym. "
        f"Zwróć tylko i wyłącznie gotową komendę, bez żadnych wyjaśnień, komentarzy, kodów blokowych ani opisów. "
        f"Jeśli nie da się tego zrobić – zwróć słowo `false`."
    )

    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}]
        )
        command = response.choices[0].message.content.strip()

        # Walidacja odpowiedzi
        if (
            command.lower() == "false" or
            len(command.splitlines()) > 1 or
            any(keyword in command.lower() for keyword in ["bash", "terminal", "shell", "nie", "możliwe", "przykład", "potrzebne", "skrypt", "opis", "komentarz"])
        ):
            print("⚠️ GPT wygenerował prawdopodobnie tekst, nie komendę.")
            return None

        return command

    except Exception as e:
        print(f"❌ Błąd zapytania do OpenAI: {e}")
        return None

def interpret_and_execute(phrase: str, action: str, raw_input: str, config: Config):
    memory = CommandMemoryHandler()
    command = memory.find_command(phrase, action)
    if command:
        print(f"\n🧠 Wykonuję zapamiętaną komendę: {command}")
        subprocess.run(command, shell=True)
        return

    print(f"\n❔ Brak komendy dla: {phrase} / {action}")
    print("🤖 Pytam GPT o możliwą komendę...")

    command = ask_gpt_for_command(raw_input, model=config.OPENAI_MODEL)
    if not command:
        print("❌ GPT nie zwrócił komendy.")
        return

    print(f"\n💡 GPT sugeruje:\n{command}")
    try:
        subprocess.run(command, shell=True)
    except Exception as e:
        print(f"\n❌ Błąd wykonania: {e}")
        return

    confirm = input(f"\n✅ Czy ta komenda działała poprawnie? (T/n): ").strip().lower()
    if confirm in ("", "t", "tak", "y", "yes"):
        memory.add_command(phrase, action, command)
        print("📦 Komenda zapisana do learned_commands.json.")
    else:
        print("🗑️ Komenda NIE została zapisana.")

# === Command Validator ===
class CommandValidator:
    def __init__(self, config: Config):
        self.config = config
        self.dangerous_patterns = [
            (r'rm\s+-rf\s+/', "Rekursywne usuwanie roota"),
            (r'(shutdown|reboot|poweroff|halt)', "Wyłączanie systemu"),
            (r'systemctl\s+(stop|disable)\s+', "Zatrzymywanie usług"),
            (r'(ifconfig|ip)\s+\w+\s+down', "Wyłączanie interfejsów"),
            (r'iptables\s+-F', "Czyszczenie firewall"),
            (r'mkfs\s+', "Formatowanie"),
            (r'chmod\s+[0]\s+/etc/(passwd|shadow|sudoers)', "Niebezpieczne uprawnienia"),
            (r'echo\s+.+\s+>\s+/etc/', "Nadpisywanie systemowych plików"),
            (r':\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\};', "Fork bomb"),
            (r'nc\s+-l', "Otwieranie portów"),
            (r'ssh\s+-[fNR]', "Niebezpieczne opcje SSH"),
        ]
        self.warning_patterns = [
            (r'rm\s', "Usuwanie plików"),
            (r'apt\s+(install|remove|purge)', "Zarządzanie pakietami"),
            (r'(yum|dnf|pacman)\s+(install|remove|-S|-R)', "Zarządzanie pakietami"),
            (r'(chmod|chown)\s+', "Zmiana uprawnień/właściciela"),
            (r'(mv|cp)\s+\S+\s+\S+', "Operacje na plikach"),
            (r'dd\s+', "Operacje na dysku"),
            (r'git\s+(push|reset|checkout)', "Operacje Git"),
            (r'curl\s+\S+', "Pobieranie plików"),
            (r'wget\s+\S+', "Pobieranie plików"),
        ]
        self.dangerous_keywords = [
            "shutdown", "poweroff", "reboot", "halt", "init 0",
            "rm -rf", "mkfs", ":(){", "dd if=", "wget http", "curl http"
        ]

    def validate_command(self, command: str) -> Tuple[bool, Optional[str]]:
        if not self.config.SAFETY_MODE:
            return True, None

        command_lower = command.strip().lower()

        # ❌ Blokada skrótowych komend typu "wyłącz"
        if command_lower in ["wyłącz", "reboot", "poweroff", "shutdown", "halt"]:
            return False, "❌ Komenda zbyt ogólna lub potencjalnie niebezpieczna – zablokowana."

        # ❌ Blokada po słowach-kluczach
        for keyword in self.dangerous_keywords:
            if keyword in command_lower:
                return False, f"❌ Blokada bezpieczeństwa: zawiera zakazane słowo: {keyword}"

        # ❌ Blokada zabronionych ścieżek
        for blocked in self.config.BLACKLISTED_DIRS:
            matches = re.findall(r'[\s\'"](/[^\'"\s]+)', command_lower)
            for path in matches:
                if path.startswith(blocked):
                    return False, f"Zabroniona ścieżka: {blocked}"

        # ❌ Blokada dopasowania regex
        for pattern, description in self.dangerous_patterns:
            if re.search(pattern, command_lower):
                return False, f"Niebezpieczna operacja: {description}"

        # ⚠️ Ostrzeżenie
        for pattern, description in self.warning_patterns:
            if re.search(pattern, command_lower):
                return True, f"Wymaga potwierdzenia: {description}"

        return True, None

# === File Operations ===
class FileOperations:
    def __init__(self, config: Config):
        self.config = config

    def _is_safe(self, path: str) -> bool:
        abs_path = os.path.abspath(path)
        return any(abs_path.startswith(allowed) for allowed in self.config.ALLOWED_DIRS) and \
               not any(abs_path.startswith(blocked) for blocked in self.config.BLACKLISTED_DIRS)

    def read_file(self, path: str) -> Optional[str]:
        if not self._is_safe(path):
            return None
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except:
            return None

    def write_file(self, path: str, content: str) -> bool:
        if not self._is_safe(path):
            return False
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except:
            return False

    def append_to_file(self, path: str, content: str) -> bool:
        if not self._is_safe(path):
            return False
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            return True
        except:
            return False

    def delete_file(self, path: str) -> bool:
        if not self._is_safe(path):
            return False
        try:
            os.remove(path)
            return True
        except:
            return False

class CommandExecutor:
    def __init__(self, config: Config, inspector: SystemInspector):
        self.config = config
        self.inspector = inspector

    def execute(self, command: str) -> Tuple[bool, str]:
        interaktywne = [
            "matrix.py", "htop", "top", "vim", "nano", "less", "more",
            "watch", "nmtui", "alsamixer", "python3", "bash", "ssh"
        ]

        # Jeśli to komenda interaktywna – uruchom w tej samej sesji terminalowej
        if any(prog in command for prog in interaktywne):
            print(f"[INTERAKTYWNY] {command}")
            os.system(command)
            self.log_command("INTERAKTYWNY", command)
            return True, "[Program interaktywny uruchomiony w tej samej sesji]"

        try:
            result = subprocess.run(
                command,
                shell=True,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=60
            )
            status = "WYKONANO" if result.returncode == 0 else "BŁĄD"
            output = result.stdout if result.returncode == 0 else result.stderr
            self.log_command(status, command, output)
            return result.returncode == 0, output
        except subprocess.TimeoutExpired:
            self.log_command("TIMEOUT", command, "Przekroczono czas wykonania")
            return False, "⏰ Przekroczono czas wykonania komendy"
        except Exception as e:
            self.log_command("BŁĄD", command, str(e))
            return False, str(e)

    def log_command(self, status: str, command: str, output: str = ""):
        print(f"[{status}] {command}")
        if output:
            print(output)

# === Device Commands Helper (fuzzy matching, aliases, multi-target) ===
class DeviceCommandHelper:
    DEVICE_ALIASES = {
        # Światła – klasyczne
        "pierwsze światło": "światło 1",
        "światło pierwsze": "światło 1",
        "światło numer jeden": "światło 1",
        "światło numer 1": "światło 1",
        "drugie światło": "światło 2",
        "światło numer dwa": "światło 2",
        "światło numer 2": "światło 2",
        "oba światła": ["światło 1", "światło 2"],
        "wszystkie światła": ["światło 1", "światło 2"],

        # Lampy – aliasy
        "lampa 1": "światło 1",
        "pierwsza lampa": "światło 1",
        "lampa numer jeden": "światło 1",
        "lampa 2": "światło 2",
        "druga lampa": "światło 2",
        "lampa numer dwa": "światło 2",
        "wszystkie lampy": ["światło 1", "światło 2"],
        "obie lampy": ["światło 1", "światło 2"]
    }

    @staticmethod
    def load_device_commands(plik: str = "/home/hal/HALbridge/device_commands.json") -> dict:
        try:
            with open(plik, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ Nie udało się załadować komend urządzeń: {e}")
            return {}

    @staticmethod
    def interpret_command(text: str, commands: dict) -> Optional[str]:
        import difflib

        text = text.lower()
        actions = {
            "włącz": ["włącz", "zaświeć", "odpal"],
            "wyłącz": ["wyłącz", "zgaś", "zgasz", "wyłączyć"]
        }

        # Rozpoznaj akcję
        action = None
        for key, aliases in actions.items():
            if any(a in text for a in aliases):
                action = key
                break

        if not action:
            print("❓ Nie rozpoznano akcji (włącz/wyłącz)")
            return None

        # Usuń akcję z tekstu
        for alias in actions[action]:
            text = text.replace(alias, "")
        raw_device = text.strip()

        # Sprawdź aliasy
        if raw_device in DeviceCommandHelper.DEVICE_ALIASES:
            devices = DeviceCommandHelper.DEVICE_ALIASES[raw_device]
            if isinstance(devices, str):
                devices = [devices]
        else:
            # Fuzzy match tylko po nazwie urządzenia
            names = list(commands.keys())
            match = difflib.get_close_matches(raw_device, names, n=1, cutoff=0.6)
            if not match:
                print(f"❌ Nie znaleziono dopasowania fuzzy dla: '{raw_device}'")
                return None
            devices = [match[0]]

        # Zbierz komendy
        cmds = []
        for d in devices:
            cmd = commands.get(d, {}).get(action)
            if cmd:
                print(f"➡️ {action} → {d}")
                cmds.append(cmd)
            else:
                print(f"⚠️ Brak komendy dla: {action} → {d}")

        if not cmds:
            return None
        return " && ".join(cmds)

class GPTChatAPI:
    def __init__(self, config: Config):
        self.config = config
        self.inspector = SystemInspector()
        self.validator = CommandValidator(config)
        self.executor = CommandExecutor(config, self.inspector)
        self.file_ops = FileOperations(config)
        self.session_memory = SessionMemory(config)
        self.device_helper = DeviceCommandHelper()
        self._history: List[Dict] = []
        self.client = None
        self._init_openai()
        self.system_info = SystemInspector.get_system_info()

    def _init_openai(self):
        if OpenAI and os.getenv("OPENAI_API_KEY"):
            self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        else:
            self.client = None

    def run_command(self, cmd: str) -> str:
        print(f"[WYKONAJ RAW] {cmd}")
        match = re.search(r"###(.*?)###", cmd, re.DOTALL)
        if match:
            cmd = match.group(1).strip()
            print(f"[WYKONAJ CZYSTE] {cmd}")
        else:
            cmd = cmd.strip()
            print(f"[WYKONAJ BEZ ###] {cmd}")

        valid, msg = self.validator.validate_command(cmd)
        if not valid:
            return msg or "❌ Komenda została zablokowana."
        if msg:
            print(f"⚠️ Ostrzeżenie: {msg}")

        success, output = self.executor.execute(cmd)
        self._add_to_history(cmd, output)
        return output

    def ask_ai(self, prompt: str, *, execute: bool = True) -> str:
        if not self.client:
            return self.local_gpt(prompt)

        try:
            response = self.client.chat.completions.create(
                model=self.config.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": self._get_context_prompt()},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=1000,
            )

            answer = response.choices[0].message.content.strip()
            ans_low = answer.lower().strip()

            # Tryb "tylko tekst": nic nie wykonuj, tylko zwróć treść
            if not execute:
                self._add_to_history(prompt, answer)
                return answer

            # Tryb wykonawczy: tylko jeśli AI jawnie poda komendę
            if ans_low.startswith("wykonaj:"):
                cmd = answer.split(":", 1)[1].strip()
                valid, msg = self.validator.validate_command(cmd)
                if not valid:
                    return msg or "❌ Komenda zablokowana."
                if msg:
                    print(f"⚠️ Ostrzeżenie: {msg}")
                return self.run_command(cmd)

            m = re.search(r"```(?:bash|sh)?\s*([\s\S]*?)```", answer, re.IGNORECASE)
            if m:
                cmd = m.group(1).strip()
                valid, msg = self.validator.validate_command(cmd)
                if not valid:
                    return msg or "❌ Komenda zablokowana."
                if msg:
                    print(f"⚠️ Ostrzeżenie: {msg}")
                return self.run_command(cmd)

            # Zwykła odpowiedź tekstowa
            self._add_to_history(prompt, answer)
            return answer

        except Exception as e:
            print(f"❌ Błąd zapytania do OpenAI: {e}")
            return self.local_gpt(prompt)

    def local_gpt(self, prompt: str) -> str:
        return f"🔌 [Offline] Nie mogę połączyć się z OpenAI. Prompt był: {prompt}"

    def read_file(self, path: str) -> str:
        content = self.file_ops.read_file(path)
        self._add_to_history(f"read {path}", content[:200] if content else "Brak treści")
        return content if content else "❌ Nie udało się odczytać pliku"

    def write_file(self, path: str, content: str) -> str:
        if self.file_ops.write_file(path, content):
            self._add_to_history(f"write {path}", content)
            return "✅ Zapisano"
        return "❌ Błąd zapisu"

    def get_history(self) -> List[Dict]:
        return self._history

    def device_command(self, text: str) -> Optional[str]:
        commands = self.device_helper.load_device_commands()
        cmd = self.device_helper.interpret_command(text, commands)
        if cmd:
            return self.run_command(cmd)
        return None

    def _add_to_history(self, command: str, output: str):
        self._history.append({
            "command": command,
            "output": output,
            "timestamp": datetime.now().isoformat()
        })
        self._history = self._history[-self.config.MAX_HISTORY:]

    def _get_context_prompt(self) -> str:
        context = [
            "Jesteś inteligentnym asystentem terminalowym. Masz następujące informacje o systemie:",
            f"System: {self.system_info.get('system', 'N/A')} {self.system_info.get('release', 'N/A')}",
            f"Procesor: {self.system_info.get('processor', 'N/A')} ({self.system_info.get('cpu_cores', 'N/A')} cores)",
            f"Pamięć: {self.system_info.get('memory', {}).get('total', 0)}",
            f"Użytkownik: {self.system_info.get('current_user', 'N/A')}",
            f"Katalog domowy: {os.path.expanduser('~')}",
            "\nOstatnie komendy:"
        ]

        for item in self._history[-5:]:
            out = item.get('output') or ""
            context.append(f"- {item['command']} (output: {out[:50]}...)")

        context.append("\nZasady odpowiedzi:")
        context.append("Jeśli użytkownik zadaje pytanie ogólne (np. o książki), odpowiedz normalnie tekstem.")
        context.append("Formaty WYKONAJ:/PLIK:/PYTANIE: stosuj tylko, gdy dotyczy to systemu, plików lub operacji terminalowych.")

        context.append("\nFormat odpowiedzi:")
        context.append("WYKONAJ: <komenda> - dla komend do wykonania")
        context.append("PLIK: <operacja> <ścieżka> - dla operacji na plikach")
        context.append("PYTANIE: <pytanie> - dla zapytań o system")

        return "\n".join(context)


# === Auto-Update (z kontrolą SHA256) ===
def auto_update(config: Config):
    try:
        url = config.AUTO_UPDATE_URL
        hash_url = config.AUTO_UPDATE_HASH_URL
        response = requests.get(url, timeout=5)
        hash_resp = requests.get(hash_url, timeout=5)
        if response.status_code == 200 and hash_resp.status_code == 200:
            remote_code = response.text.strip()
            remote_hash = hash_resp.text.strip().split()[0]
            sha256 = hashlib.sha256(remote_code.encode('utf-8')).hexdigest()
            if sha256 != remote_hash:
                print(f"❌ SHA256 nie zgadza się! Aktualizacja przerwana.")
                return
            current_code = Path(__file__).read_text(encoding="utf-8")
            if remote_code != current_code:
                print("🟡 Nowa wersja kodu dostępna.")
                confirm = input("Aktualizować plik? [Y/n]: ").strip().lower()
                if confirm in ["", "y", "yes", "tak"]:
                    Path(__file__).write_text(remote_code, encoding="utf-8")
                    print("✅ Terminal zaktualizowany. Uruchom ponownie.")
                    exit(0)
            else:
                print("🔄 Kod już aktualny.")
        else:
            print("⚠️ Błąd pobierania aktualizacji lub hasha.")
    except Exception as e:
        print(f"❌ Autoaktualizacja nie powiodła się: {e}")


def _extract_imports_from_python(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                imports.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module.split(".")[0])
    return sorted(imports)

def _is_stdlib_module(mod: str) -> bool:
    # Python 3.10+ ma sys.stdlib_module_names
    std = getattr(sys, "stdlib_module_names", None)
    if std is not None:
        return mod in std
    # Fallback heurystyczny
    common_std = {
        "sys","os","time","re","json","math","random","datetime","pathlib","subprocess","threading",
        "queue","select","socket","termios","tty","signal","shutil","tempfile","logging","itertools","functools",
        "collections","heapq","bisect","argparse","typing","enum","dataclasses","hashlib","hmac","base64","zlib",
        "statistics","sqlite3","unicodedata","traceback","inspect","ast","importlib","glob","fnmatch","getpass"
    }
    return mod in common_std

def _missing_third_party_modules(code: str) -> List[str]:
    mods = _extract_imports_from_python(code)
    missing = []
    for m in mods:
        if _is_stdlib_module(m):
            continue
        if importlib.util.find_spec(m) is None:
            missing.append(m)
    return missing

def _compile_check(code: str) -> Optional[str]:
    try:
        compile(code, "<generated>", "exec")
        return None
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno}, col {e.offset})"

def _extract_code_block_from_llm(raw: str) -> str:
    m_py = re.search(r"```(?:python|py)\s*([\s\S]*?)```", raw, re.IGNORECASE)
    m_any = re.search(r"```+\s*([\s\S]*?)```+", raw) if not m_py else None
    if m_py:
        code = m_py.group(1).strip()
    elif m_any:
        code = m_any.group(1).strip()
    else:
        code = raw.strip()
    cleaned_lines = []
    for line in code.splitlines():
        ls = line.strip()
        if not ls:
            cleaned_lines.append(line)
            continue
        if ls.upper().startswith("WYKONAJ"):
            continue
        if ls.startswith("[") and ls.endswith("]"):
            continue
        if ls.startswith("/bin/sh:"):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()

def _repair_prompt(original_code: str, error_text: str, missing_mods: List[str]) -> str:
    advice = []
    if missing_mods:
        advice.append(
            "Usuń wszystkie zależności zewnętrzne i użyj wyłącznie standardowej biblioteki Pythona. "
            f"Te moduły są niedostępne i nie mogą być użyte: {', '.join(missing_mods)}."
        )
    if error_text:
        advice.append(f"Popraw błąd kompilacji/uruchomienia: {error_text}")
    advice.append(
        "Zachowaj tę samą funkcjonalność. Zwróć WYŁĄCZNIE gotowy kod w Pythonie w bloku ```python``` bez komentarzy."
    )
    return (
        "Napraw poniższy program w Pythonie.\n\n"
        "Oto kod do poprawy:\n\n"
        "```python\n" + original_code + "\n```\n\n"
        + "\n".join(advice)
    )


# === CLI Main Loop (STRICT + tryb "code" z agresywną sanitacją) ===
def main():
    config = Config()

    if not os.getenv("OPENAI_API_KEY") and OpenAI:
        print("🔐 Nie wykryto klucza OpenAI API.")
        key = input("Podaj swój klucz OpenAI API: ").strip()
        os.environ["OPENAI_API_KEY"] = key
        print("✅ Klucz zapisany w zmiennej środowiskowej.")

    api = GPTChatAPI(config)

    print("🌐 GPT TERMINAL FUSION v2 – wpisz 'exit' aby zakończyć")
    print("📁 read <plik> – odczyt pliku")
    print("✏️ write <plik> <treść> – zapis do pliku")
    print("📡 !komenda – wykonanie polecenia systemowego (bez NLP)")
    print("🔄 update – autoaktualizacja")
    print("🧠 ai <prompt> – rozmowa z LLM (NIE wykonuje komend)")
    print("🧩 code [plik.py] <prompt> – wygeneruj kod z LLM, zapisz do pliku i uruchom")
    print("🔦 komendy urządzeń (np. 'włącz światło 1') – sterowanie sprzętem")
    print("⚙️ Tryb: STRICT — wszystko poza 'ai ', 'code ' i znacznikami traktuję jako KOMENDĘ (NLP→bash).")

    while True:
        try:
            user_input = input("hal@ai-term:~$ ").strip()
            if not user_input:
                continue

            if user_input.lower() == "exit":
                print("👋 Do zobaczenia, Jaśnie Panie!")
                break

            if user_input.lower() == "update":
                auto_update(config)
                continue

            if user_input.startswith("read "):
                path = user_input[5:].strip()
                print(api.read_file(path))
                continue

            if user_input.startswith("write "):
                parts = shlex.split(user_input)
                if len(parts) >= 3:
                    path, content = parts[1], " ".join(parts[2:])
                    print(api.write_file(path, content))
                else:
                    print("❌ Błąd składni: write <plik> <treść>")
                continue

            if user_input.startswith("!"):
                cmd = user_input[1:]
                print(api.run_command(cmd))
                continue

            if user_input.startswith("ai "):
                prompt = user_input[3:].strip()
                print(api.ask_ai(prompt))
                continue


            # Tryb CODE: generowanie kodu, preflight, auto-naprawa i uruchomienie
            if user_input.startswith("code "):
                rest = user_input[5:].strip()

                # Parsowanie nazwy pliku
                filename = None
                m = re.match(r'^([A-Za-z0-9_\-./]+?\.(?:py|sh|bash|js|ts|go|rb|pl|php))\s*:\s*(.*)$', rest)
                if m:
                    filename, prompt = m.group(1), m.group(2).strip()
                else:
                    parts = rest.split(maxsplit=1)
                    if len(parts) == 2 and re.match(r'^[A-Za-z0-9_\-./]+?\.(?:py|sh|bash|js|ts|go|rb|pl|php)$', parts[0]):
                        filename, prompt = parts[0], parts[1].strip()
                    else:
                        prompt = rest
                        ts = time.strftime("%Y%m%d_%H%M%S")
                        filename = f"ai_code_{ts}.py"

                # 1) Pobierz surową odpowiedź bez wykonywania czegokolwiek
                raw_answer = api.ask_ai(prompt, execute=False)
                code_block = _extract_code_block_from_llm(raw_answer)

                # 2) Preflight: wytnij zależności zewnętrzne automatycznie (1 próba)
                missing = _missing_third_party_modules(code_block) if filename.lower().endswith(".py") else []
                syntax_err = _compile_check(code_block) if filename.lower().endswith(".py") else None

                repair_attempts = 0
                max_attempts = 2  # łącznie 2 próby naprawy

                while filename.lower().endswith(".py") and (missing or syntax_err) and repair_attempts < max_attempts:
                    repair_attempts += 1
                    repair_instructions = _repair_prompt(code_block, syntax_err or "", missing)
                    raw_fix = api.ask_ai(repair_instructions, execute=False)
                    fixed = _extract_code_block_from_llm(raw_fix)
                    # Re-walidacja
                    code_block = fixed
                    missing = _missing_third_party_modules(code_block)
                    syntax_err = _compile_check(code_block)

                # 3) Zapisz plik
                ok = api.file_ops.write_file(filename, code_block)
                if not ok:
                    try:
                        with open(filename, "w", encoding="utf-8") as f:
                            f.write(code_block)
                    except Exception as e:
                        print(f"❌ Nie udało się zapisać pliku {filename}: {e}")
                        continue

                print(f"💾 Zapisano wygenerowany kod do {filename}")

                # 4) Ustal runner
                low = filename.lower()
                if low.endswith(".py"):
                    runner = f"python3 {shlex.quote(filename)}"
                elif low.endswith((".sh", ".bash")):
                    try:
                        st = os.stat(filename)
                        os.chmod(filename, st.st_mode | stat.S_IEXEC)
                    except Exception:
                        pass
                    runner = f"bash {shlex.quote(filename)}"
                elif low.endswith(".js"):
                    runner = f"node {shlex.quote(filename)}"
                elif low.endswith(".ts"):
                    runner = f"ts-node {shlex.quote(filename)}"
                elif low.endswith(".go"):
                    runner = f"go run {shlex.quote(filename)}"
                elif low.endswith(".rb"):
                    runner = f"ruby {shlex.quote(filename)}"
                elif low.endswith(".pl"):
                    runner = f"perl {shlex.quote(filename)}"
                elif low.endswith(".php"):
                    runner = f"php {shlex.quote(filename)}"
                else:
                    print("ℹ️ Nieznane rozszerzenie – plik zapisany, ale nie uruchamiam automatycznie.")
                    continue

                # 5) Walidacja i uruchomienie
                valid, msg = api.validator.validate_command(runner)
                if not valid:
                    print(msg or "❌ Komenda zablokowana.")
                    continue
                if msg:
                    print(f"⚠️ Ostrzeżenie: {msg}")

                run_out = api.run_command(runner)

                # 6) Jeśli runtime wywalił ImportError/ModuleNotFoundError lub stacktrace Pythona, spróbuj 1x auto-fix
                if low.endswith(".py"):
                    need_runtime_fix = False
                    err_text = ""
                    if isinstance(run_out, str) and ("ModuleNotFoundError" in run_out or "ImportError" in run_out or "Traceback (most recent call last):" in run_out):
                        need_runtime_fix = True
                        err_text = run_out.strip()

                    if need_runtime_fix and repair_attempts < max_attempts:
                        repair_attempts += 1
                        repair_instructions = _repair_prompt(code_block, err_text, _missing_third_party_modules(code_block))
                        raw_fix = api.ask_ai(repair_instructions, execute=False)
                        code_block = _extract_code_block_from_llm(raw_fix)
                        # Zapis i ponowny run
                        ok = api.file_ops.write_file(filename, code_block)
                        if not ok:
                            with open(filename, "w", encoding="utf-8") as f:
                                f.write(code_block)
                        print(f"🔁 Poprawka zapisana do {filename}, uruchamiam ponownie...")
                        print(api.run_command(runner))
                continue


            if "###" in user_input:
                print(api.run_command(user_input))
                continue

            if "$&$" in user_input:
                try:
                    prompt = user_input.split("$&$")[1].strip()
                except IndexError:
                    prompt = user_input.replace("$&$", "").strip()
                print(api.ask_ai(prompt))
                continue

            result = api.device_command(user_input)
            if result is not None:
                print(result)
                continue

            # STRICT: wszystko inne traktuj jako polecenie do wykonania (NLP→bash)
            interpret_and_execute(user_input, "wykonaj", user_input, config)

        except KeyboardInterrupt:
            print("\n⏹️ Przerwano – wpisz 'exit' aby zakończyć.")
        except Exception as e:
            print(f"❌ Nieoczekiwany błąd: {e}")

# === Wejście programu ===
if __name__ == "__main__":
    diagnose_and_heal()
    main()
