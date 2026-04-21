"""
Cienki adapter serwerowy do aktualnego agenta HALbridge.

Cel:
- odseparować server_api.py od szczegółów gpt_chat_v4.py
- zapewnić jedno miejsce integracji z agentem
- przygotować grunt pod przyszłe wydzielenie AgentCore
"""

from __future__ import annotations
from modules.agent_core import ask as core_ask


def ask(prompt: str, session_id: str = "server_api") -> str:
    return core_ask(prompt, session_id=session_id)
