from __future__ import annotations

from modules.agent_device_bridge import device_command as agent_device_command
from modules.hardware_adapter import get_bridge

bridge = get_bridge()

def device_command(text: str) -> str | None:
    return agent_device_command(text, bridge)
