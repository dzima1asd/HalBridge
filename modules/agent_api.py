import json
import os
import re
import subprocess
from typing import Optional

from openai import OpenAI

from modules.runtime_core import Config, MemoryStore, RotatingLogger, TokenMeter, ensure_dirs
from modules.project_tools import ProjectManager, GitManager
from modules.system_tools import FileOps, CommandValidator, CommandExecutor, HttpTool
from modules.module_runner import ModuleRunner
from modules.agent_codegen_runtime import build_codegen_filename, build_run_command, register_generated_code
from modules.codegen_utils import compile_check, missing_third_party, repair_prompt, sanitize_llm_code
from modules import code_registry

class GPTChatAPI:
    def __init__(self, cfg: Config, session_id: str = "default", registry=None):
        self.cfg = cfg
        ensure_dirs(cfg)
        self.logger = RotatingLogger(cfg)
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY")) if OpenAI and os.getenv("OPENAI_API_KEY") else None
        self.validator = CommandValidator(cfg)
        self.exec = CommandExecutor(cfg, self.logger)
        self.projects = ProjectManager(cfg)
        self.files = FileOps(cfg, self.projects)
        self.memory = MemoryStore(cfg)
        self.meter = TokenMeter(cfg, self.logger)
        self.http = HttpTool(cfg, self.logger)
        self.git = GitManager(cfg, self.projects, self.logger)
        self.session_id = session_id
        self.memory.ensure_session(session_id)
        self.logger.log("agent.start", model=cfg.OPENAI_MODEL, usd_to_pln=cfg.USD_TO_PLN)
        self.modules = ModuleRunner(cfg, self.logger)
        self.registry = registry

    def _system_prompt(self) -> str:
        rules = [
            # ================================================
            #  ROLA I ŚRODOWISKO
            # ================================================
            "Jesteś asystentem terminalowym działającym wewnątrz środowiska Linux/Ubuntu użytkownika 'hal'.",
            "Pracujesz na tym samym systemie, z którego przychodzi polecenie.",

"Pracujesz jako lokalny agent systemu HALbridge.",
"Masz możliwość wykonywania komend systemowych, operacji na plikach oraz sterowania urządzeniami (np. MQTT, światła, przekaźniki).",
"Jeśli użytkownik wydaje polecenie sterowania urządzeniem, NIE ODPOWIADASZ że nie masz dostępu – zamiast tego próbujesz je zinterpretować lub zwracasz błąd wykonania.",

            "Masz dostęp do narzędzi (function calling) oraz możesz generować bloki ```bash```.",

            # ================================================
            #  ZASADA ZERO ZGADYWANIA – LOKALNY SYSTEM
            # ================================================
            "Jeśli pytanie DOTYCZY LOKALNEGO SYSTEMU (np. w tym Ubuntu), w szczególności:",
            "- rozmiaru pliku (kilobajty, bajty, MB, itp.),",
            "- liczby linii w pliku, istnienia pliku, jego ścieżki, daty modyfikacji, uprawnień, właściciela,",
            "- zawartości katalogu, listy plików, drzew katalogów,",
            "- procesów, PID-ów, zużycia CPU/RAM, wersji pakietów,",
            "- jakichkolwiek danych, które mogą być sprawdzone komendą systemową w Ubuntu:",
            "",
            "  → NIE MASZ PRAWA zgadywać ani wymyślać odpowiedzi.",
            "  → NIE WOLNO Ci podawać liczby, rozmiaru, opisu ani podsumowania BEZ wcześniejszego wywołania komendy.",
            "",
            "W takiej sytuacji TWOJA PIERWSZA ODPOWIEDŹ MUSI wyglądać w JEDEN z dwóch sposobów:",
            "",
            "  1) Jako wywołanie narzędzia `shell_execute` (function calling) z poprawną komendą bash,",
            "     np. {\"tool\": \"shell_execute\", \"cmd\": \"stat -c '%s' gpt_chat_v4.py\"},",
            "",
            "  ALBO",
            "",
            "  2) Jako blok:",
            "     ```bash",
            "     <konkretna_komenda>",
            "     ```",
            "",
            "Nie wolno Ci w takiej sytuacji zwracać samej liczby (np. \"104\"), tekstu typu \"ma 100 KB\"",
            "ani żadnego innego opisu bez komendy. Każda taka odpowiedź jest BŁĘDNA względem tych zasad.",
            "Jeśli nie jesteś pewien, czy pytanie dotyczy lokalnego systemu, PRZYJMUJ, ŻE DOTYCZY i zachowuj się jak wyżej.",

            # ================================================
            #  BASH / BLOKI KONSOLI
            # ================================================
            "Blok ```bash``` generujesz wszędzie tam, gdzie naturalnym narzędziem jest polecenie terminalowe.",
            "W bloku ```bash``` nie umieszczasz komentarzy ani objaśnień – tylko czyste polecenia.",
            "Po wykonaniu komendy agent zwróci wynik, który możesz później interpretować w kolejnych turach.",

            # ================================================
            #  NARZĘDZIA (FUNCTION CALLING)
            # ================================================
            "Masz do dyspozycji narzędzia: shell_execute, file_access, file_chunk, file_write, dir_list, file_search, web_fetch, browser_query.",
            "Narzędzi używaj, gdy trzeba realnie odczytać pliki, katalogi, dane z sieci lub wykonać komendę.",
            "Narzędzia wywołujesz TYLKO w ramach function calling, nie w zwykłym tekście odpowiedzi.",

            # ================================================
            #  KOD PYTHON
            # ================================================
            "Jeśli użytkownik prosi o kod w Pythonie:",
            "- korzystaj wyłącznie ze standardowej biblioteki Pythona,",
            "- NIE używaj pip, requests, keyboard, termcolor ani zewnętrznych pakietów,",
            "- zwracaj kod w czystym bloku ```python``` bez poleceń do shella.",

            # ================================================
            #  INTERNET
            # ================================================
            "Do pobierania aktualnych danych z internetu używaj narzędzia web_fetch.",
            "Jeśli użytkownik nie podał adresu URL, możesz użyć Binga: https://www.bing.com/search?q=<zapytanie>.",
            "Do analizy HTML (tytuły, linki, streszczenie) używaj browser_query na treści pobranej przez web_fetch.",
            "Nie pokazuj użytkownikowi surowych tool-calli ani JSON – opisuj wynik po ludzku.",

            # ================================================
            #  AUTOKOREKTA I NEWSY
            # ================================================
            "Jeśli pytanie zawiera oczywiste literówki lub błędy w nazwach, popraw je w myślach i użyj poprawionej wersji.",
            "Dla newsów i ważnych informacji najpierw próbuj znaleźć dane w zaufanych źródłach (np. Reuters, AP News, BBC),",
            "a dopiero potem w innych wynikach wyszukiwarki.",

            # ================================================
            #  SYSTEM PLIKÓW
            # ================================================
            "Treści plików nigdy nie zgaduj – zawsze używaj file_access lub file_chunk.",
            "Zawartości katalogów nigdy nie zgaduj – zawsze używaj dir_list.",
        ]
        return "\n".join(rules) + "\n"

# --------- Deklaracja narzędzi (tools) dla GPT API ---------


    def _tools_schema(self):
        return [
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Pobiera stronę internetową przez moduł hal_webfetch",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Adres URL lub zapytanie"
                            }
                        },
                        "required": ["url"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "browser_query",
                    "description": "Analizuje HTML strony jak tryb przeglądarki (browser-mode)",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Adres URL, której dotyczy analiza"
                            },
                            "html": {
                                "type": "string",
                                "description": "Pełna treść HTML pobrana wcześniej przez web_fetch"
                            }
                        },
                        "required": ["url", "html"]
                    }
                }
            },
            {
            "type": "function",
            "function": {
                "name": "file_access",
                "description": "Czyta zawartość pliku z systemu użytkownika.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Ścieżka pliku do odczytu"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
    "type": "function",
    "function": {
        "name": "dir_list",
        "description": "Listuje pliki i katalogi w folderze",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "file_search",
        "description": "Przeszukuje treść plików we wskazanym katalogu",
        "parameters": {
            "type": "object",
            "properties": {
                "root": {"type": "string"},
                "pattern": {"type": "string"}
            },
            "required": ["root", "pattern"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "file_chunk",
        "description": "Czyta fragment pliku od podanego offsetu",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer"},
                "size": {"type": "integer"}
            },
            "required": ["path"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "file_write",
        "description": "Zapisuje treść do pliku",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["path", "content"]
        }
    }
},
{
    "type": "function",
    "function": {
        "name": "shell_execute",
        "description": "Wykonuje komendę systemową w powłoce bash i zwraca stdout/stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"}
            },
            "required": ["cmd"]
        }
    }
}
        ]

# ------ NIE PRZEKRACZANIE KONTEKSTU
    @staticmethod
    def _maybe_autosummarize(text: str) -> str:
        """
        Lekki mechanizm zabezpieczający przed przekroczeniem kontekstu.
        Jeśli odpowiedź modelu jest absurdalnie długa (np. >15k znaków),
        skracamy ją, aby nie zatkać pamięci sesji.

        Jest statyczna, bo bywa wywoływana jako GPTChatAPI._maybe_autosummarize(answer).
        """
        if not text:
            return text

        # jeśli tekst jest krótki → zwracamy bez zmian
        if len(text) < 15000:
            return text

        # skrót dla ekstremalnych odpowiedzi
        return text[:12000] + "\n\n[... skrócono autosummarize ...]\n"

        # jeśli tekst jest krótki → zwracamy bez zmian
        if len(text) < 15000:
            return text

        # skrót dla ekstremalnych odpowiedzi
        return text[:12000] + "\n\n[... skrócono autosummarize ...]\n"

# --------- LLM interakcje ---------
    def ask_ai_grounded(self, context_prompt: str, *, note: str = "grounded_web") -> str:
        if not self.client:
            return "Brak danych."

        messages = [
            {
                "role": "system",
                "content": (
                    "Odpowiadasz wyłącznie na podstawie przekazanego kontekstu i źródeł. "
                    "Nie używaj narzędzi. Nie zgaduj. Nie korzystaj z wiedzy spoza dostarczonego tekstu. "
                    "Jeśli źródła są zbyt słabe, śmieciowe albo nie zawierają odpowiedzi, napisz dokładnie: 'Brak danych.'. "
                    "Jeśli są dane, odpowiedz zwięźle, konkretnie i po polsku."
                )
            },
            {"role": "user", "content": context_prompt},
        ]

        self.logger.log(
            "llm.grounded_request",
            model=self.cfg.OPENAI_MODEL,
            note=note,
            prompt_len=len(context_prompt),
        )

        resp = self.client.chat.completions.create(
            model=self.cfg.OPENAI_MODEL,
            temperature=0.0,
            max_tokens=self.cfg.OPENAI_MAX_TOKENS,
            messages=messages,
        )

        msg = resp.choices[0].message
        answer = (msg.content or "").strip()

        try:
            u = resp.usage
            self.meter.add_usage(
                model=self.cfg.OPENAI_MODEL,
                prompt_tokens=int(getattr(u, "prompt_tokens", 0)),
                completion_tokens=int(getattr(u, "completion_tokens", 0)),
                note=note,
            )
        except Exception:
            pass

        return answer or "Brak danych."

    def ask_ai_local(
        self,
        prompt: str,
        *,
        note: str = "local_knowledge",
        context_mode: str = "session",
    ) -> str:
        if not self.client:
            return f"🔌 [Offline] Brak OPENAI_API_KEY. Prompt: {prompt}"

        user_prompt = (prompt or "").strip()
        mode = (context_mode or "session").strip().lower()
        if mode == "stateless":
            recent_messages = []
        elif mode == "light":
            recent_messages = self.memory.get_recent_messages(self.session_id, limit=2)
        else:
            mode = "session"
            recent_messages = self.memory.get_recent_messages(self.session_id, limit=8)

        messages = [
            {
                "role": "system",
                "content": (
                    "Odpowiadasz po polsku, rzeczowo i normalnie. "
                    "To jest tryb local_knowledge: nie używaj narzędzi, nie korzystaj z webu, "
                    "nie zgaduj faktów bieżących. "
                    "Dla pytań definicyjnych, porad ogólnych, przepisów, pytań interpretacyjnych "
                    "i wiedzy ogólnej odpowiadaj bezpośrednio z wiedzy modelu. "
                    "Nie odpowiadaj 'brak danych', jeśli możesz udzielić sensownej odpowiedzi ogólnej. "
                    "Jeśli pytanie jest opinią lub oceną, zaznacz że to ocena, a nie twardy fakt. "
                    "Korzystaj z kontekstu poprzednich wypowiedzi w tej rozmowie tylko wtedy, gdy jest potrzebny. "
                    "Jeśli użytkownik pyta zaimkiem lub skrótem myślowym, odnieś to do ostatniego sensownego tematu rozmowy. "
                    "Jeśli widzisz słowo, które wygląda na literówkę, błąd lub niejednoznaczne określenie, "
                    "nie wymyślaj definicji ani faktów. Najpierw krótko dopytaj o znaczenie albo zaznacz najbardziej prawdopodobną interpretację. "
                    "Gdy nie masz pewności, wybieraj ostrożność zamiast fantazjowania."
                )
            },
        ]
        messages += recent_messages
        messages.append({"role": "user", "content": user_prompt})

        self.logger.log(
            "llm.local_request",
            model=self.cfg.OPENAI_MODEL,
            note=note,
            prompt_len=len(user_prompt),
            history_count=len(recent_messages),
            context_mode=mode,
        )

        resp = self.client.chat.completions.create(
            model=self.cfg.OPENAI_MODEL,
            temperature=self.cfg.OPENAI_TEMPERATURE,
            max_tokens=self.cfg.OPENAI_MAX_TOKENS,
            messages=messages,
        )

        msg = resp.choices[0].message
        answer = (msg.content or "").strip()

        try:
            u = resp.usage
            self.meter.add_usage(
                model=self.cfg.OPENAI_MODEL,
                prompt_tokens=int(getattr(u, "prompt_tokens", 0)),
                completion_tokens=int(getattr(u, "completion_tokens", 0)),
                note=note,
            )
        except Exception:
            pass

        self.memory.add_message(self.session_id, "user", user_prompt)
        self.memory.add_message(self.session_id, "assistant", answer)
        self._maybe_autosummarize(answer)

        return answer or "Nie udało się wygenerować odpowiedzi."

    def ask_ai_stateless(self, prompt: str, *, execute: bool = True, note: str = "") -> str:
        return self.ask_ai(prompt, execute=execute, note=note, context_mode="stateless")

    def ask_ai_light(self, prompt: str, *, execute: bool = True, note: str = "") -> str:
        return self.ask_ai(prompt, execute=execute, note=note, context_mode="light")

    def ask_ai_local_stateless(self, prompt: str, *, note: str = "local_knowledge") -> str:
        return self.ask_ai_local(prompt, note=note, context_mode="stateless")

    def ask_ai_local_light(self, prompt: str, *, note: str = "local_knowledge") -> str:
        return self.ask_ai_local(prompt, note=note, context_mode="light")

    def run_web_research(self, prompt: str, intent: Optional[dict] = None) -> str:
        if not self.registry:
            return (
                "Brak podpiętego registry dla web research. "
                "Nie mogę wykonać wyszukiwania źródłowego."
            )

        from modules.web_research import run_web_research

        safe_intent = intent or {"queries": [prompt]}
        return run_web_research(self, self.registry, safe_intent, prompt)

    def ask_ai(
        self,
        prompt: str,
        *,
        execute: bool = True,
        note: str = "",
        context_mode: str = "session",
    ) -> str:
        if not self.client:
            return f"🔌 [Offline] Brak OPENAI_API_KEY. Prompt: {prompt}"

        mode = (context_mode or "session").strip().lower()
        if mode == "stateless":
            recent_messages = []
        elif mode == "light":
            recent_messages = self.memory.get_recent_messages(self.session_id, limit=2)
        else:
            mode = "session"
            recent_messages = self.memory.get_recent_messages(self.session_id, limit=10)

        # --- Budowa kontekstu ---
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages += recent_messages
        messages.append({"role": "user", "content": prompt})

        estimated_messages_chars = sum(len(str(m.get("content", ""))) for m in messages)
        self.logger.log(
            "llm.request",
            model=self.cfg.OPENAI_MODEL,
            note=note,
            prompt_len=len(prompt),
            estimated_messages_chars=estimated_messages_chars,
            message_count=len(messages),
            context_mode=mode,
            history_count=len(recent_messages),
        )

        # --- PĘTLA MULTI-TURN ---
        while True:
            resp = self.client.chat.completions.create(
                model=self.cfg.OPENAI_MODEL,
                temperature=self.cfg.OPENAI_TEMPERATURE,
                max_tokens=self.cfg.OPENAI_MAX_TOKENS,
                messages=messages,
                tools=self._tools_schema(),
                tool_choice="auto",
            )

            msg = resp.choices[0].message
            answer = (msg.content or "").strip()
            tool_calls = getattr(msg, "tool_calls", None)

            # --- Jeśli nie ma tool-call → kończymy rozmowę ---
            if not tool_calls:
                # log tokenów
                try:
                    u = resp.usage
                    self.meter.add_usage(
                        model=self.cfg.OPENAI_MODEL,
                        prompt_tokens=int(getattr(u, "prompt_tokens", 0)),
                        completion_tokens=int(getattr(u, "completion_tokens", 0)),
                        note=note or ("execute" if execute else "noexec"),
                    )
                except Exception:
                    pass

                # historia
                self.memory.add_message(self.session_id, "user", prompt)
                self.memory.add_message(self.session_id, "assistant", answer)
                self._maybe_autosummarize(answer)

                # auto-wykonanie bash
                if execute:
                    low = answer.lower()

                    if low.startswith("wykonaj:"):
                        cmd = answer.split(":", 1)[1].strip()
                        ok, warn = self.validator.validate(cmd)
                        if not ok:
                            return warn or "❌ Komenda zablokowana."
                        _, out = self.exec.run(cmd)
                        return out

                    m = re.search(
                        r"```(?:bash|sh)?\s*([\s\S]*?)```",
                        answer,
                        re.IGNORECASE
                    )
                    if m:
                        cmd = m.group(1).strip()
                        ok, warn = self.validator.validate(cmd)
                        if not ok:
                            return warn or "❌ Komenda zablokowana."
                        _, out = self.exec.run(cmd)
                        return out

                return answer

            # --- Jeśli są tool-calle → wykonujemy je i kontynuujemy pętlę ---
            # 1. Zapisujemy wiadomość asystenta zawierającą deklarację tool-call
            messages.append({
                "role": "assistant",
                "content": answer,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ],
            })

            # 2. Wykonujemy każde narzędzie
            for call in tool_calls:
                name = call.function.name
                args = json.loads(call.function.arguments)

                try:
                    if name == "shell_execute":
                        r = subprocess.run(
                            args["cmd"],
                            shell=True,
                            capture_output=True,
                            text=True
                        )
                        out = {
                            "ok": True,
                            "cmd": args["cmd"],
                            "stdout": r.stdout,
                            "stderr": r.stderr,
                            "returncode": r.returncode,
                        }

                    else:
                        out = self.registry.invoke(name, args)

                except Exception as e:
                    out = {"error": str(e)}

                # 3. Zwracamy wynik narzędzia do modelu
                tool_payload = json.dumps(out, ensure_ascii=False)
                max_tool_chars = int(getattr(self.cfg, "OPENAI_TOOL_RESULT_MAX_CHARS", 4000))
                if len(tool_payload) > max_tool_chars:
                    tool_payload = (
                        tool_payload[:max_tool_chars]
                        + "\n...[tool output truncated]..."
                    )

                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": tool_payload,
                })

    # --------- CODE: generuj → napraw → zapisz → auto-commit → uruchom ---------
    def generate_and_run_code(self, prompt: str, filename: Optional[str] = None) -> str:
        # --- FAZA 2: analiza promptu ---
        try:
            from modules import intelligence
            analysis = intelligence.analyze_prompt(prompt)
            task_type = analysis["type"]
            profile = analysis["profile"]
            expected_output = analysis["expected_output"]
            print(f"[INTELIGENCE] typ={task_type}, profil={profile}, wynik={expected_output}")
        except Exception as e:
            print(f"[INTELIGENCE] błąd analizy: {e}")
            analysis = {"type": "text", "profile": "headless", "expected_output": "tekst"}
            profile = "headless"
        # --- Analiza promptu i ustalenie profilu sandboxa ---
        task_meta = None
        profile = "headless"
        expected_output = None
        if 'intelligence' in globals() and intelligence:
            try:
                task_meta = intelligence.analyze_prompt(prompt)
                profile = task_meta.get("profile", "headless")
                expected_output = task_meta.get("expected_output")
                task_type = task_meta.get("type")
                self._last_task_meta = task_meta  # opcjonalnie: zapamiętaj do diagnostyki
                print(f"[INTELLIGENCE] Typ: {task_type}, Profil: {profile}, Cel: {expected_output}")
            except Exception as e:
                print(f"[INTELLIGENCE] Błąd analizy promptu: {e}")
                profile = "headless"
                expected_output = None

        self.logger.log("code.gen.start", prompt_len=len(prompt))
        raw = self.ask_ai(prompt, execute=False, note="code_gen")
        code = sanitize_llm_code(raw)

        # Preflight i auto-naprawa
        attempts = 0
        max_attempts = 2
        err = compile_check(code)
        missing = missing_third_party(code)
        while (err or missing) and attempts < max_attempts:
            attempts += 1
            self.logger.log("code.gen.fix_attempt", attempt=attempts, err=bool(err), missing=",".join(missing))
            fix_raw = self.ask_ai(repair_prompt(code, err or "", missing), execute=False, note="code_fix")
            code = sanitize_llm_code(fix_raw)
            err = compile_check(code)
            missing = missing_third_party(code)

        # Nazwa pliku
        if not filename:
            ts = None
            filename = build_codegen_filename(filename)

        # Zapis do sandboxa projektu
        if not self.files.write(filename, code):
            self.logger.log("code.save.error", filename=filename)
            return f"❌ Nie udało się zapisać pliku (sandbox): {filename}"
        abs_target = self.projects.current_path() / filename
        print(f"💾 Zapisano kod do {abs_target}")
        self.logger.log("code.save.ok", path=str(abs_target), bytes=len(code.encode('utf-8')))

        # --- FAZA 3b: rejestracja wygenerowanego kodu ---
        register_generated_code(
            abs_target,
            getattr(self, "active_project", None),
            getattr(self, "_last_task_meta", None),
            code_registry
        )


        # Auto-commit po zapisie
        try:
            self.git.autocommit(f"codegen: {filename}")
        except Exception:
            pass

        # Sprawdzenie składni
        syn = compile_check(code)
        if syn:
            self.logger.log("code.compile.error", err=syn)
            return f"❌ Błąd komp.: {syn}"

        # Uruchom wg rozszerzenia
        run_cmd = build_run_command(abs_target)
        if not run_cmd:
            return "ℹ️ Plik zapisany, ale rozszerzenie nieznane – nie uruchamiam."

        ok, warn = self.validator.validate(run_cmd)
        if not ok:
            self.logger.log("code.run.blocked", cmd=run_cmd, reason=warn)
            return warn or "❌ Komenda zablokowana."
        success, out = self.exec.run(run_cmd)

        # Jedna próba auto-fix po runtime errorze
        if not success and ("Traceback (most recent call last):" in out or "ModuleNotFoundError" in out or "ImportError" in out):
            self.logger.log("code.runtime.error", cmd=run_cmd)
            fix_raw = self.ask_ai(repair_prompt(code, out, missing_third_party(code)), execute=False, note="code_runtime_fix")
            code2 = sanitize_llm_code(fix_raw)
            if code2 and code2 != code:
                if not self.files.write(filename, code2):
                    self.logger.log("code.runtime.save_error", filename=filename)
                    return f"❌ Nie udało się zapisać poprawki (sandbox): {filename}"
                print(f"🔁 Poprawka zapisana do {abs_target}, uruchamiam ponownie...")
                syn2 = compile_check(code2)
                if syn2:
                    self.logger.log("code.runtime.compile_error", err=syn2)
                    return f"❌ Błąd kompilacji po poprawce: {syn2}"
                _, out2 = self.exec.run(run_cmd)
                return out2
        return out
