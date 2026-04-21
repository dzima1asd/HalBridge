from __future__ import annotations

from modules.hardware_bridge import HardwareBridge

_bridge = None


def get_bridge() -> HardwareBridge:
    global _bridge
    if _bridge is None:
        _bridge = HardwareBridge()
    return _bridge


def run(command: str) -> dict:
    bridge = get_bridge()
    raw = bridge.execute(command)

    return {
        "ok": True,
        "handled": True,
        "command": command,
        "result_type": type(raw).__name__,
        "raw_result": raw,
    }
