from __future__ import annotations
import os
# Helpery codegen przeniesione z gpt_chat_v4.py
from typing import List, Optional
import re


def extract_imports(code: str) -> List[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                mods.add(n.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module.split(".")[0])
    return sorted(mods)


def missing_third_party(code: str) -> List[str]:
    mods = extract_imports(code)
    std = getattr(sys, "stdlib_module_names", None)
    missing = []
    for m in mods:
        if std is not None and m in std:
            continue
        if std is None and m in {
            "sys","os","time","re","json","random","datetime","pathlib","subprocess",
            "select","socket","termios","tty","signal","shutil","tempfile","logging",
            "itertools","functools","collections","argparse","typing","enum","dataclasses",
            "hashlib","importlib","urllib","ast","traceback",
        }:
            continue
        if importlib.util.find_spec(m) is None:
            missing.append(m)
    return missing


def compile_check(code: str) -> Optional[str]:
    try:
        compile(code, "<generated>", "exec")
        return None
    except SyntaxError as e:
        return f"SyntaxError: {e.msg} (line {e.lineno}, col {e.offset})"


def sanitize_llm_code(raw: str) -> str:
    m_py = re.search(r"```(?:python|py)\s*([\s\S]*?)```", raw, re.IGNORECASE)
    m_any = re.search(r"```+\s*([\s\S]*?)```+", raw) if not m_py else None
    code = (m_py.group(1) if m_py else (m_any.group(1) if m_any else raw)).strip()
    cleaned = []
    for line in code.splitlines():
        ls = line.strip()
        if not ls:
            cleaned.append(line); continue
        if ls.upper().startswith("WYKONAJ"):
            continue
        if ls.startswith("[") and ls.endswith("]"):
            continue
        if ls.startswith("/bin/sh:"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def repair_prompt(original_code: str, error_text: str, missing_mods: List[str]) -> str:
    advice = []
    if missing_mods:
        advice.append(
            "Usuń wszystkie zależności spoza standardowej biblioteki Pythona: "
            + ", ".join(missing_mods) + "."
        )
    if error_text:
        advice.append(f"Popraw błąd: {error_text}")
    advice.append("Zwróć WYŁĄCZNIE gotowy kod w Pythonie w bloku ```python``` bez komentarzy.")
    return (
        "Napraw poniższy program w Pythonie.\n\n"
        "Kod do poprawy:\n\n"
        "```python\n" + original_code + "\n```\n\n" + "\n".join(advice)
    )

PROMPT_RULES_FILE = os.path.expanduser("~/HALbridge/prompt_rules.txt")
