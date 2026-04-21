from __future__ import annotations

import re

from modules.agent_codegen_runtime import build_run_command


def _extract_filename_and_code(response: str) -> tuple[str | None, str | None]:
    text = (response or "").strip()
    if not text:
        return None, None

    filename = None

    m = re.search(r'^FILENAME:\s*([A-Za-z0-9_\-./]+\.(?:py|sh|bash))\s*$', text, re.M)
    if m:
        filename = m.group(1).strip()

    code = None

    m = re.search(r'```python\s*([\s\S]*?)```', text, re.I)
    if not m:
        m = re.search(r'```bash\s*([\s\S]*?)```', text, re.I)
    if not m:
        m = re.search(r'```sh\s*([\s\S]*?)```', text, re.I)
    if not m:
        m = re.search(r'```([\s\S]*?)```', text, re.I)

    if m:
        code = m.group(1).strip()

    return filename, code


def _looks_like_valid_codegen(filename: str, code: str) -> bool:
    name = (filename or "").lower()
    body = (code or "").strip()

    if not body:
        return False

    if name.endswith(".py"):
        python_markers = (
            "import ",
            "print(",
            "def ",
            "class ",
            "for ",
            "while ",
            "if ",
            "__name__",
        )
        return any(marker in body for marker in python_markers)

    if name.endswith(".sh") or name.endswith(".bash"):
        shell_markers = (
            "#!/bin/bash",
            "#!/usr/bin/env bash",
            "#!/bin/sh",
            "#!/usr/bin/env sh",
            "echo ",
            "date",
            "for ",
            "while ",
            "if ",
            "case ",
            "$(",
            "exit ",
        )
        return any(marker in body for marker in shell_markers)

    generic_markers = (
        "print(",
        "echo ",
        "def ",
        "for ",
        "if ",
    )
    return any(marker in body for marker in generic_markers)


def _build_codegen_prompt(user_prompt: str, explicit_filename: str | None) -> str:
    if explicit_filename:
        return (
            "Wygeneruj wyłącznie kod do pliku o nazwie: "
            f"{explicit_filename}. "
            "Zwróć tylko jeden blok kodu fenced, bez opisu."
            "\n\nZADANIE:\n"
            + user_prompt
        )

    return (
        "Masz wygenerować mały plik wykonywalny. "
        "Najpierw podaj jedną linię w formacie: FILENAME: nazwa_pliku.py "
        "albo .sh albo .bash. "
        "Następnie zwróć dokładnie jeden blok kodu fenced. "
        "Nie dodawaj opisu ani komentarza poza tym formatem."
        "\n\nZADANIE:\n"
        + user_prompt
    )

def _normalize_natural_codegen_request(line: str) -> str | None:
    text = (line or "").strip()
    if not text:
        return None

    low = text.lower()

    if low.startswith("code "):
        return text[5:].strip()

    prefixes = (
        "napisz skrypt ",
        "napisz program ",
        "stwórz skrypt ",
        "stworz skrypt ",
        "stwórz program ",
        "stworz program ",
        "wygeneruj skrypt ",
        "wygeneruj program ",
        "zrób skrypt ",
        "zrob skrypt ",
        "zrób program ",
        "zrob program ",
    )

    for prefix in prefixes:
        if low.startswith(prefix):
            return text[len(prefix):].strip()

    return None


def handle_codegen_line(line: str, api):
    rest = _normalize_natural_codegen_request(line)
    if not rest:
        return False, None

    explicit_filename = None
    m = re.match(r'^([A-Za-z0-9_\-./]+?\.(?:py|sh|bash))\s*:\s*(.*)$', rest)

    if m:
        explicit_filename, user_prompt = m.group(1), m.group(2).strip()
    else:
        user_prompt = rest

    try:
        llm_prompt = _build_codegen_prompt(user_prompt, explicit_filename)
        response = api.ask_ai_local(llm_prompt)

        suggested_filename, code = _extract_filename_and_code(response)

        filename = explicit_filename or suggested_filename
        if not filename:
            filename = "generated_script.py"

        if not code:
            return True, "[CODEGEN][ERR] LLM nie zwrócił poprawnego bloku kodu"

        # prosta walidacja jakości
        if len(code.splitlines()) < 1:
            return True, "[CODEGEN][ERR] pusty kod"

        if not _looks_like_valid_codegen(filename, code):
            return True, "[CODEGEN][WARN] kod wygląda podejrzanie (brak typowych konstrukcji dla tego typu pliku)"


        api.files.write(filename, code)

        run_cmd = build_run_command(filename)
        return True, f"[CODEGEN] zapisano: {filename}\n[CODEGEN] uruchom: {run_cmd}"

    except Exception as e:
        return True, f"[CODEGEN][ERR] {type(e).__name__}: {e}"
