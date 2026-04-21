# HALbridge Runtime Map

## Active Runtime

### Agent
- `gpt_chat_v3.py`
- status: ACTIVE
- rola: główny agent lokalny / CLI / logika wykonawcza

### Hardware Bridge
- `modules/hardware_bridge.py`
- status: ACTIVE
- rola: interpretacja i wykonanie komend urządzeń

### Web Fetch
- `modules/tools/web_fetch.py`
- `hal_webfetch.py`
- status: ACTIVE
- rola: pobieranie i ekstrakcja treści internetowych

### Tool Registry / Intent Layer
- `modules/tools/registry.py`
- `modules/intents/`
- `modules/policy/router.py`
- status: ACTIVE
- rola: routing narzędzi, rozpoznawanie intencji, logika wyboru ścieżki

---

## Legacy

### Self Modifier
- `self_modifier.py`
- status: LEGACY / DISABLED
- powód: powiązanie z architekturą `gpt_chat_v2`, brak bezpiecznego modelu walidacji zmian

### Old Server
- `halbridge_server.py`
- status: LEGACY
- powód: historyczne sprzężenie z `gpt_chat_v2` i starszą architekturą serwera

---

## Deferred / Out of Scope for Current Refactor

### Camera System
- status: DEFERRED
- uwaga: nie jest jeszcze połączony z głównym systemem agenta

### Finance / ETL
- status: DEFERRED
- uwaga: nie jest jeszcze połączony z głównym systemem agenta

---

## Current Architectural Direction

Docelowy kierunek refaktoryzacji:
1. zachować `gpt_chat_v3.py` jako aktualny rdzeń agenta
2. oprzeć wykonanie sprzętowe na `modules/hardware_bridge.py`
3. utrzymać jedną oficjalną ścieżkę web fetch:
   - `modules/tools/web_fetch.py`
   - `hal_webfetch.py`
4. zbudować nowy, odchudzony serwer API pod v3
5. nie używać `self_modifier.py` w aktywnym runtime

---

## Notes

- `halbridge_server.py` nie jest bazą do dalszego rozwoju
- `self_modifier.py` pozostaje tylko jako artefakt historyczny
- kamera i finanse są poza bieżącym zakresem refaktoryzacji
- kolejnym krokiem jest zaprojektowanie nowego serwera API pod v3
