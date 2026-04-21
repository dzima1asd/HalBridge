from __future__ import annotations

"""
Tymczasowy rdzeń serwerowy agenta HALbridge.

Cel:
- dać jedno stabilne wejście do logiki agenta
- odseparować adaptery i serwer od szczegółów gpt_chat_v4.py
- przygotować grunt pod późniejsze wydzielanie prawdziwego AgentCore
"""

from modules.agent_answer import answer_prompt


def ask(prompt: str, session_id: str = "server_api") -> str:
    return answer_prompt(prompt, session_id=session_id)
