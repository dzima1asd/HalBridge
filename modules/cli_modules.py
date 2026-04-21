from __future__ import annotations

import shlex


def handle_modules_line(line: str, api) -> tuple[bool, str | None]:
    if line == "modules list":
        mods = api.modules.list()
        if mods:
            return True, "Dostępne moduły:\n" + "\n".join(f"- {m}" for m in mods)
        return True, "(brak modułów)"

    if line.startswith("module info "):
        parts = shlex.split(line)
        if len(parts) >= 3:
            name = parts[2]
            return True, api.modules.info(name)
        return True, "❌ Składnia: module info <nazwa>"

    if line.startswith("module run "):
        parts = shlex.split(line)
        if len(parts) >= 3:
            name = parts[2]
            args = " ".join(parts[3:])
            ok, out = api.modules.run(name, args)
            return True, out
        return True, "❌ Składnia: module run <nazwa> [args...]"

    return False, None
