from __future__ import annotations

import re
import shlex
import shutil
from pathlib import Path


def handle_logs_runtime(line: str, api, cfg) -> tuple[bool, str | None]:
    if line.startswith("logs tail"):
        parts = shlex.split(line)
        n = 100
        if len(parts) == 3 and parts[2].isdigit():
            n = int(parts[2])
        return True, api.logger.tail(n)

    if line.startswith("logs grep "):
        pattern = line[len("logs grep "):].strip()
        path = Path(cfg.APP_LOG_FILE)
        if not path.exists():
            return True, "(brak logów)"

        pat = re.compile(pattern, re.IGNORECASE)
        out = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for L in f:
                if pat.search(L):
                    out.append(L.rstrip())

        return True, "\n".join(out) if out else "(brak trafień)"

    if line.startswith("logs export "):
        outp = line[len("logs export "):].strip()
        srcp = Path(cfg.APP_LOG_FILE)
        if not srcp.exists():
            return True, "❌ Brak logów do eksportu"

        try:
            Path(outp).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(srcp, outp)
            return True, f"✅ Wyeksportowano do {outp}"
        except Exception as e:
            return True, f"❌ Błąd eksportu: {e}"

    if line == "logs clear":
        try:
            Path(cfg.APP_LOG_FILE).unlink(missing_ok=True)
            for i in range(1, cfg.LOG_BACKUPS + 1):
                Path(f"{cfg.APP_LOG_FILE}.{i}").unlink(missing_ok=True)
            return True, "🧹 Logi wyczyszczone"
        except Exception as e:
            return True, f"❌ Błąd czyszczenia: {e}"

    return False, None
