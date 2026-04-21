# HALbridge Web Runtime Map

## Canonical Web Runtime Path
- modules/tools/web_fetch.py
- hal_webfetch.py
- modules/tools/browser_query.py

## Separate Interactive Browser Layer
- modules/browser_bridge.py

## Optional / Active Subsystem
- modules/tools/web_orchestrator.py

## Legacy / Non-canonical
- modules/web_tool.py
- modules/web_parser.py
- modules/web_bridge_copy.py

## Notes
- server_api.py korzysta z web przez modules/web_adapter.py
- web_fetch.py jest publiczną bramą pobierania stron
- hal_webfetch.py renderuje strony przez Playwright
- browser_query.py analizuje HTML
- web_orchestrator.py jest poza kanoniczną ścieżką fetch, ale używany przez gpt_chat_v3
