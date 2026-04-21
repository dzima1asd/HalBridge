from __future__ import annotations

import json

from modules.voice_state import load_voice_state


def main() -> int:
    state = load_voice_state()
    print(json.dumps({
        "ok": True,
        "voice_config": state,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
