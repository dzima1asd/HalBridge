# modules/intents/engine_v2.py
"""
IntentEngineV2 – wersja minimalna, czysta i bezpieczna.
--------------------------------------------------------------------
Rola:
- być ultra-cienką warstwą nad komendą `ai`,
- nie zgadywać domen (finanse, pliki, newsy…),
- nie generować żadnych heurystyk ani reguł,
- NIE DODAWAĆ żadnych instrukcji do system prompt,
- pełną inteligencję oddać GPTChatAPI (ask_ai),
- zezwalać modelowi wykonywać komendy bash i narzędzia.

Mechanika:
- handle_ai() zawsze zwraca handled=True,
- API.ask_ai(prompt, execute=True) uruchamia auto-wykonanie:
    • "wykonaj: <cmd>"
    • bloki ```bash ...```
- jeśli GPTChatAPI zwróci błąd, przechwytujemy i zwracamy użytkownikowi.
"""

from typing import Optional, Tuple


class IntentEngineV2:
    def __init__(self, api, registry=None, debug: bool = True) -> None:
        """
        :param api: instancja GPTChatAPI z gpt_chat_v4.py
        :param registry: przyszłościowy ToolRegistry
        :param debug: czy wypisywać logi z IntentEngineV2
        """
        self.api = api
        self.registry = registry
        self.debug = debug

    # ------------------------------------------------------------------
    # GŁÓWNY ENTRY-POINT dla `ai <polecenie>`
    # ------------------------------------------------------------------
    def handle_ai(self, prompt: str) -> Tuple[bool, Optional[str]]:
        """
        Wersja minimalna:
        - nie ma żadnych własnych reguł logiki,
        - nie analizuje promptu,
        - całkowicie polega na GPTChatAPI.ask_ai(),
        - execute=True aktywuje autowykonanie poleceń bash.

        Zwraca:
            (True, odpowiedź tekstowa)
        """
        self._log(f"handle_ai: {prompt!r}")

        try:
            answer = self.api.ask_ai(
                prompt,
                execute=True,
                note="ai_local_v2",
            )
        except Exception as e:
            self._log(f"błąd w api.ask_ai: {e}")
            return True, f"❌ Błąd API: {e}"

        # zabezpieczenie: ask_ai może zwrócić pusty string lub None
        if not answer:
            return True, "⚠️ Brak odpowiedzi z modelu."

        return True, answer

    # ------------------------------------------------------------------
    # LOG
    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        try:
            if self.debug:
                print(f"[IEv2] {msg}")
        except Exception:
            pass
