import os

from modules.intents.engine_v2 import IntentEngineV2
from modules.runtime_objects import build_runtime_objects


def bootstrap_app(Config, ensure_dirs, OpenAI, GPTChatAPI, banner, registry):
    bridge, browser = build_runtime_objects()

    cfg = Config()
    ensure_dirs(cfg)

    if not os.getenv("OPENAI_API_KEY") and OpenAI:
        try:
            key = input("🔐 Brak OPENAI_API_KEY. Podaj klucz: ").strip()
            os.environ["OPENAI_API_KEY"] = key
        except EOFError:
            print("\n👋 Do zobaczenia (EOF).")
            return None

    api = GPTChatAPI(cfg, session_id="local")
    banner(cfg, api)

    intent_engine_v2 = IntentEngineV2(api, registry=registry, debug=True)
    registry.register("mqtt", "modules.tools.adapters.mqtt")

    return {
        "cfg": cfg,
        "api": api,
        "bridge": bridge,
        "browser": browser,
        "intent_engine_v2": intent_engine_v2,
    }
