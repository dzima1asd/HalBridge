from __future__ import annotations

from modules.agent_utils import safe_json as agent_safe_json, urlencode as agent_urlencode
from modules.agent_intent_rules import ai_intent as agent_ai_intent


def ai_intent(user_query: str) -> dict:
    return agent_ai_intent(user_query)


def safe_json(raw, default=None):
    return agent_safe_json(raw, default=default)


def urlencode(txt: str) -> str:
    return agent_urlencode(txt)
