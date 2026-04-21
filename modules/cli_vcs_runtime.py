from __future__ import annotations

import shlex


def handle_vcs_runtime(line: str, api) -> tuple[bool, str | None]:
    if line == "vcs init":
        return True, api.git.init()

    if line == "vcs ensure":
        return True, api.git.init()

    if line == "vcs status":
        return True, api.git.status()

    if line.startswith("vcs oneline"):
        parts = shlex.split(line)
        n = 20
        if len(parts) >= 3 and parts[2].isdigit():
            n = int(parts[2])
        return True, api.git.log(n)

    if line.startswith("vcs diff"):
        parts = shlex.split(line)
        path_arg = parts[2] if len(parts) >= 3 else None
        return True, api.git.diff(path_arg)

    if line.startswith("vcs save:"):
        msg = line.split(":", 1)[1].strip()
        if not msg:
            return True, '❌ Podaj komunikat, np. vcs save: "komentarz"'
        return True, api.git.commit(msg)

    if line.startswith("vcs commit "):
        msg = line[len("vcs commit "):].strip().strip('"').strip("'")
        if not msg:
            return True, '❌ Podaj komunikat: vcs commit "wiadomość"'
        return True, api.git.commit(msg)

    return False, None
