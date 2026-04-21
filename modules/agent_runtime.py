from __future__ import annotations

"""
Runtime warstwy agenta HALbridge.

Cel:
- jedno miejsce odpowiedzialne za tworzenie i cache instancji GPTChatAPI
- odseparowanie lifecycle agenta od agent_core
- przygotowanie gruntu pod dalsze wydzielanie kodu z gpt_chat_v4.py
"""

_api_cache = {}


def create_api(session_id: str = "server_api"):
    import gpt_chat_v4 as agent_module

    cfg_cls = getattr(agent_module, "Config", None)
    api_cls = getattr(agent_module, "GPTChatAPI", None)

    if cfg_cls is None or api_cls is None:
        raise RuntimeError("gpt_chat_v4.py does not expose Config and GPTChatAPI")

    cfg = cfg_cls()
    registry = getattr(agent_module, "registry", None)
    return api_cls(cfg, session_id=session_id, registry=registry)


def get_api(session_id: str = "server_api"):
    key = session_id
    if key not in _api_cache:
        _api_cache[key] = create_api(session_id=session_id)
    return _api_cache[key]


def reset_api(session_id: str | None = None):
    global _api_cache
    if session_id is None:
        _api_cache = {}
    else:
        _api_cache.pop(session_id, None)
