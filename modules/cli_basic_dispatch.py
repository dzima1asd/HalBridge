from __future__ import annotations

from modules.cli_meta_utils import show_help


def handle_basic_cli(line: str) -> tuple[bool, str | None, bool]:
    low = (line or "").lower().strip()

    if low in ("exit", "quit", "q"):
        return True, "👋 Do zobaczenia.", True

    if low in ("help", "?"):
        return True, show_help(), False

    return False, None, False
