# HALbridge canonical runtime map

## Active entrypoints
- gpt_chat_v3.py
- server_api.py

## Active routing / knowledge
- modules/query_router.py
- modules/route_types.py
- modules/source_policy.py
- modules/live_data_router.py
- modules/live_data_fx.py
- modules/live_data_weather.py
- modules/tools/web_orchestrator.py
- modules/tools/web_fetch.py

## Active device / execution
- modules/hardware_adapter.py
- modules/hardware_bridge.py
- modules/agent_device_layer.py
- modules/tools/registry.py

## Local LLM paths
- GPTChatAPI.ask_ai()
- GPTChatAPI.ask_ai_local()
- GPTChatAPI.ask_ai_grounded()

## Rules now
- factual routes must not guess from model memory
- local_knowledge may use ask_ai_local()
- current_facts/news_research must answer only from gathered evidence or return "Brak danych." / "Brak pewnych danych z aktualnych źródeł."

## Legacy / not canonical
- halbridge_server.py
- self_modifier.py
- modules/web_tool.py
- modules/web_parser.py
- modules/web_bridge_copy.py
- all *.bak
- archive/*
