import os

from openai import OpenAI

from modules.runtime_core import Config, ensure_dirs
from modules.cli_meta_utils import banner
from modules.tools.registry import registry
from modules.intents.engine_v2 import IntentEngineV2
from modules.cli_entry import run_cli
from modules.runtime_objects import build_runtime_objects
from modules.agent_api import GPTChatAPI


bridge = None
browser = None
GLOBAL_API = None


def parse_time_to_seconds(value: str) -> int:
    value = value.strip()
    if ":" in value:
        minutes, seconds = value.split(":", 1)
        return int(minutes) * 60 + int(seconds)
    return int(value)


def main():
    global bridge, browser, GLOBAL_API

    cfg = Config()
    ensure_dirs(cfg)
    bridge, browser = build_runtime_objects()

    if not os.getenv("OPENAI_API_KEY") and OpenAI:
        try:
            key = input("🔐 Brak OPENAI_API_KEY. Podaj klucz: ").strip()
            os.environ["OPENAI_API_KEY"] = key
        except EOFError:
            print("\n👋 Do zobaczenia (EOF).")
            return

    api = GPTChatAPI(cfg, session_id="local", registry=registry)
    GLOBAL_API = api

    banner(cfg, api)

    intent_engine_v2 = IntentEngineV2(api, registry=registry, debug=True)
    registry.register("mqtt", "modules.tools.adapters.mqtt")

    run_cli(api, cfg, browser, bridge, registry)


if __name__ == "__main__":
    main()
