from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_HISTORY_PATH = Path.home() / "HALbridge/logs/voice_history.jsonl"


def append_voice_history(event: dict[str, Any], history_path: str | None = None) -> dict[str, Any]:
    path = Path(history_path) if history_path else DEFAULT_HISTORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        **event,
    }

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {
        "ok": True,
        "history_path": str(path),
    }


if __name__ == "__main__":
    raise SystemExit("voice_history.py is a module, not a standalone runner")
