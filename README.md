Architektura gpt_chat_v4.py
gpt_chat_v4.py jest głównym interfejsem agenta HalBridge.
Pełni rolę:
obsługi konwersacji (LLM),
interakcji z użytkownikiem (CLI),
integracji z narzędziami,
przekazywania poleceń do Execution Kernel.
👉 Jest to warstwa sterująca, a nie wykonawcza.
1. Główne zadania agenta
Odbieranie poleceń użytkownika
Obsługa konwersacji z OpenAI
Przekazywanie poleceń do kernela
Obsługa tool-calli
Wyświetlanie wyników
2. Execution Kernel (centrum systemu)
Kernel odpowiada za wykonanie poleceń.
📁 modules/execution_models.py
definiuje:
ExecutionRequest
ExecutionResult
👉 wspólny format danych w systemie
📁 modules/execution_router.py
główna logika wykonawcza
analizuje polecenie
wybiera co zrobić
👉 to jest faktyczny „mózg wykonawczy”
📁 modules/execution_classifier.py
klasyfikuje polecenia:
device
conversation
inne
👉 decyduje kierunek działania
3. Routing i wykonanie
Przepływ:
powstaje ExecutionRequest
router analizuje polecenie
classifier wybiera typ
wywoływany jest moduł
powstaje ExecutionResult
4. Warstwa narzędzi (TOOLS)
📁 modules/tools/
Zestaw narzędzi dostępnych dla systemu i AI.
🗂 Pliki
📁 file_access.py
odczyt plików
📁 file_write.py
zapis plików
📁 file_search.py
wyszukiwanie w plikach
📁 dir_list.py
listowanie katalogów
🌐 Web / Playwright
📁 web_fetch.py
pobieranie stron (Playwright)
renderowanie JavaScript
📡 Integracje
📁 mqtt.py
komunikacja MQTT
📁 shelly_mqtt_listener.py
odbiór stanów urządzeń Shelly
🔧 Registry
📁 registry.py
rejestr narzędzi
mapowanie nazw → funkcje
5. Warstwa sprzętowa (Device Layer)
📁 modules/agent_device_layer.py
przyjmuje polecenia typu:
„włącz światło”
tłumaczy na operacje sprzętowe
📁 modules/agent_device_bridge.py
wykonuje operacje:
MQTT
komunikacja z urządzeniami
6. Interfejsy systemu (Kernel Bridges)
📁 modules/cli_kernel_bridge.py
CLI → ExecutionRequest
📁 modules/server_kernel_bridge.py
API → ExecutionRequest
zwraca JSON
📁 modules/voice_kernel_bridge.py
voice → ExecutionRequest
integracja z TTS/STT
7. Warstwa AI
📁 modules/agent_api.py (GPTChatAPI)
komunikacja z OpenAI
obsługa tool-calli
zarządzanie historią
8. Bezpieczeństwo
📁 modules/guardrails.py
filtruje komendy
blokuje niebezpieczne operacje
9. Mapa zależności
Poniżej uproszczona mapa: kto woła kogo i którędy płynie rozkaz.
Główna ścieżka CLI
gpt_chat_v4.py
↓
modules/agent_api.py
↓
modules/cli_kernel_bridge.py
↓
modules/execution_models.py
↓
modules/execution_router.py
↓
modules/execution_classifier.py
↓
wybór ścieżki wykonania
Ścieżka urządzeń
execution_router.py
↓
modules/agent_device_layer.py
↓
modules/agent_device_bridge.py
↓
modules/tools/mqtt.py / urządzenia Shelly
Ścieżka konwersacji
execution_router.py
↓
modules/agent_api.py
↓
OpenAI / tool-calls
↓
modules/tools/registry.py
↓
konkretne narzędzie z modules/tools/
Ścieżka webowa
execution_router.py lub agent_api.py
↓
modules/tools/web_fetch.py
↓
Playwright / warstwa pobierania stron
↓
wynik tekstowy wraca do agenta
Ścieżka plikowa
execution_router.py lub agent_api.py
↓
modules/tools/registry.py
↓
file_access.py
file_write.py
file_search.py
dir_list.py
Ścieżka serwerowa
zewnętrzne API / halbridge_server.py
↓
modules/server_kernel_bridge.py
↓
ExecutionRequest
↓
execution_router.py
↓
wykonanie
↓
ExecutionResult
↓
JSON response
Ścieżka głosowa
system voice / STT
↓
modules/voice_kernel_bridge.py
↓
ExecutionRequest
↓
execution_router.py
↓
wykonanie
↓
ExecutionResult
↓
TTS / odpowiedź głosowa
10. Schemat zależności w skrócie
Plain text
gpt_chat_v4.py
 ├─ agent_api.py
 ├─ cli_kernel_bridge.py
 │   ├─ execution_models.py
 │   └─ execution_router.py
 │       ├─ execution_classifier.py
 │       ├─ agent_device_layer.py
 │       │   └─ agent_device_bridge.py
 │       │       └─ mqtt.py
 │       └─ agent_api.py
 │           └─ tools/registry.py
 │               ├─ file_access.py
 │               ├─ file_write.py
 │               ├─ file_search.py
 │               ├─ dir_list.py
 │               ├─ web_fetch.py
 │               ├─ mqtt.py
 │               └─ shelly_mqtt_listener.py
 ├─ server_kernel_bridge.py
 └─ voice_kernel_bridge.py
11. Jak to czytać praktycznie
gpt_chat_v4.py przyjmuje polecenie
bridge zamienia je na wspólny format
kernel decyduje, co z tym zrobić
wykonanie idzie do:
AI,
narzędzi,
urządzeń,
webu,
plików
👉 Czyli rdzeń systemu nie siedzi już w jednym wielkim pliku, tylko w układzie:
interfejs → kernel → wykonanie
12. Podsumowanie
System składa się z trzech głównych części:
🎯 Interfejs
gpt_chat_v4.py
🧠 Kernel
execution_router, classifier, models
⚙️ Wykonanie
tools
device layer
integracje