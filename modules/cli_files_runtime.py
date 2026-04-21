from __future__ import annotations

import shlex


def handle_files_runtime(line: str, api) -> tuple[bool, str | None]:
    if line.startswith("read "):
        path = line[5:].strip()
        txt = api.files.read(path)
        return True, txt if txt is not None else "❌ Nie udało się odczytać (sandbox)"

    if line.startswith("write "):
        parts = shlex.split(line)
        if len(parts) >= 3:
            path = parts[1]
            content = " ".join(parts[2:])
            ok = api.files.write(path, content)
            return True, "✅ Zapisano" if ok else "❌ Błąd zapisu (sandbox)"
        return True, "❌ Składnia: write <plik> <treść>"

    return False, None
