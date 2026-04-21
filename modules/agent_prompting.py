from __future__ import annotations


def build_system_prompt() -> str:
    rules = [
        "Jesteś asystentem terminalowym działającym wewnątrz środowiska Linux/Ubuntu użytkownika 'hal'.",
        "Pracujesz na tym samym systemie, z którego przychodzi polecenie.",
        "Masz dostęp do narzędzi (function calling) oraz możesz generować bloki ```bash```.",

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

        "Blok ```bash``` generujesz wszędzie tam, gdzie naturalnym narzędziem jest polecenie terminalowe.",
        "W bloku ```bash``` nie umieszczasz komentarzy ani objaśnień – tylko czyste polecenia.",
        "Po wykonaniu komendy agent zwróci wynik, który możesz później interpretować w kolejnych turach.",

        "Masz do dyspozycji narzędzia: shell_execute, file_access, file_chunk, file_write, dir_list, file_search, web_fetch, browser_query.",
        "Narzędzi używaj, gdy trzeba realnie odczytać pliki, katalogi, dane z sieci lub wykonać komendę.",
        "Narzędzia wywołujesz TYLKO w ramach function calling, nie w zwykłym tekście odpowiedzi.",

        "Jeśli użytkownik prosi o kod w Pythonie:",
        "- korzystaj wyłącznie ze standardowej biblioteki Pythona,",
        "- NIE używaj pip, requests, keyboard, termcolor ani zewnętrznych pakietów,",
        "- zwracaj kod w czystym bloku ```python``` bez poleceń do shella.",

        "Do pobierania aktualnych danych z internetu używaj narzędzia web_fetch.",
        "Jeśli użytkownik nie podał adresu URL, możesz użyć Binga: https://www.bing.com/search?q=<zapytanie>.",
        "Do analizy HTML (tytuły, linki, streszczenie) używaj browser_query na treści pobranej przez web_fetch.",
        "Nie pokazuj użytkownikowi surowych tool-calli ani JSON – opisuj wynik po ludzku.",

        "Jeśli pytanie zawiera oczywiste literówki lub błędy w nazwach, popraw je w myślach i użyj poprawionej wersji.",
        "Dla newsów i ważnych informacji najpierw próbuj znaleźć dane w zaufanych źródłach (np. Reuters, AP News, BBC),",
        "a dopiero potem w innych wynikach wyszukiwarki.",

        "Treści plików nigdy nie zgaduj – zawsze używaj file_access lub file_chunk.",
        "Zawartości katalogów nigdy nie zgaduj – zawsze używaj dir_list.",
    ]
    return "\n".join(rules) + "\n"


def build_tools_schema():
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
