HalBridge – AI Execution System

HalBridge to modułowy system wykonawczy sterowany przez AI, który łączy:

- konwersację (OpenAI),
- wykonywanie komend systemowych,
- operacje na plikach,
- automatyzację web (Playwright),
- sterowanie urządzeniami (MQTT / Shelly),
- obsługę głosu (Voice).

System oparty jest o wspólny rdzeń:

👉 Execution Kernel

---

Architektura gpt_chat_v4.py

"gpt_chat_v4.py" jest głównym interfejsem systemu.

Odpowiada za:

- komunikację z użytkownikiem,
- obsługę konwersacji (LLM),
- przekazywanie poleceń do kernela,
- obsługę tool-calli.

👉 Nie wykonuje logiki bezpośrednio – deleguje ją do Execution Kernel.

---

Execution Kernel (centrum systemu)

Kernel odpowiada za wykonanie poleceń.

modules/execution_models.py

- definiuje:
  - "ExecutionRequest"
  - "ExecutionResult"

modules/execution_router.py

- główna logika wykonawcza
- analizuje polecenia
- wybiera ścieżkę działania

modules/execution_classifier.py

- klasyfikuje polecenia:
  - device
  - conversation
  - inne

---

Przepływ działania

1. Użytkownik wydaje polecenie
2. Tworzony jest "ExecutionRequest"
3. Router analizuje polecenie
4. Klasyfikator wybiera typ
5. Wywoływany jest odpowiedni moduł
6. Powstaje "ExecutionResult"
7. Wynik trafia do użytkownika

---

Narzędzia (modules/tools)

Pliki

- file_access.py – odczyt plików
- file_write.py – zapis plików
- file_search.py – wyszukiwanie
- dir_list.py – listowanie katalogów

---

Web

- web_fetch.py – pobieranie stron (Playwright)

---

Integracje

- mqtt.py – komunikacja MQTT
- shelly_mqtt_listener.py – odbiór stanów urządzeń

---

Registry

- registry.py – mapowanie nazw narzędzi → funkcje

---

Warstwa sprzętowa

modules/agent_device_layer.py

- interpretuje polecenia typu „włącz światło”

modules/agent_device_bridge.py

- wykonuje operacje MQTT
- komunikuje się z urządzeniami

---

Interfejsy systemu

CLI

- modules/cli_kernel_bridge.py

Server

- modules/server_kernel_bridge.py

Voice

- modules/voice_kernel_bridge.py

Każdy interfejs korzysta z tego samego kernela.

---

Warstwa AI

modules/agent_api.py (GPTChatAPI)

- komunikacja z OpenAI
- obsługa tool-calli
- zarządzanie historią

---

Bezpieczeństwo

modules/guardrails.py

- filtruje komendy
- blokuje niebezpieczne operacje

---

Podsumowanie

HalBridge to:

👉 system wykonawczy z warstwą AI

- kernel realizuje logikę działania
- AI wspiera komunikację
- interfejs przekazuje polecenia

---