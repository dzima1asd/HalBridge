gpt_chat_v3.py to jest głowny plik systemu 

# Architektura gpt_chat_v3.py

`gpt_chat_v3.py` jest głównym agentem systemu HalBridge.  
To centralny moduł, który integruje:

- konwersację z modelem OpenAI,
- interpretację intencji użytkownika,
- narzędzia systemowe (tools),
- obsługę plików i projektów,
- integrację z Playwright (moduł webowy),
- kontrolę urządzeń (MQTT / Shelly),
- warstwę bezpieczeństwa,
- mechanizmy analizy i samonaprawy.

W praktyce `gpt_chat_v3.py` działa jak **mini-system operacyjny dla AI**.

---

## 1. Główne zadania agenta

1. Odbieranie poleceń użytkownika.
2. Klasyfikacja celu:
   - zwykła odpowiedź tekstowa,
   - wykonanie komendy systemowej,
   - analiza plików,
   - sterowanie sprzętem,
   - zapytanie webowe,
   - polecenie „aliasowe”,
   - tool-call wywołany przez model.
3. Przekazanie zadania do odpowiedniego modułu.
4. Zbieranie wyników, analiza wykonania, statystyki.
5. Pilnowanie bezpieczeństwa i naprawa błędów.

---

## 2. Warstwa inteligencji (LLM + analiza odpowiedzi)

`gpt_chat_v3.py` wykorzystuje:

- **GPTChatAPI** – obsługa OpenAI, konwersacja, tool-calle.
- **modules/intelligence.py** – analiza przebiegu akcji, decyzje, jak reagować na odpowiedzi modelu.
- **modules/metrics.py** – metryki powodzeń/porażek narzędzi.
- **modules/result_analyzer.py** – ocena wyniku, czy zadanie się powiodło.
- **modules/self_heal.py** – mechanizmy naprawcze (np. ponawianie akcji, autokorekta strategii).

Ta warstwa pozwala agentowi działać świadomie, adaptacyjnie i bezpiecznie.

---

## 3. Warstwa Intencji (Intent Engine)

Aby agent rozumiał polecenia w stylu:

- „włącz światło 2”  
- „pobierz stronę wp.pl”  
- „analizuj plik CSV”  
- „kliknij drugi wynik wyszukiwania”  

używa trzech modułów:

### ⚙️ 3.1. Rozpoznawanie intencji  
`modules/intents/recognizer.py`  
Określa typ polecenia:  
np. `iot.toggle`, `iot.blink`, `browser.fetch`, `system.exec`, `web.search`.

### ⚙️ 3.2. Wydobywanie parametrów  
`modules/intents/extract_slots.py`  
Wyciąga szczegóły:  
urządzenie, liczby, adresy URL, nazwy plików, czasy, etc.

### ⚙️ 3.3. Routing intencji  
`modules/policy/router.py`  
Decyduje, **który moduł wykonuje zadanie**:

- `hardware_bridge` (światła, MQTT, Shelly)
- `web_fetch` / Playwright
- `browser_controller`
- `file_access`, `file_search`, `file_write`
- `code` / wykonanie programów
- narzędzia systemowe

---

## 4. Warstwa narzędzi (TOOLS)

`gpt_chat_v3.py` rejestruje narzędzia z folderu `modules/tools/`, udostępniając je modelowi jako funkcje.

### Główne grupy:

### 🗂 Pliki
- `file_access.py` – czytanie plików  
- `file_write.py` – zapisywanie  
- `file_search.py` – wyszukiwanie w treści  
- `file_chunk.py` – dzielenie dużych plików  
- `dir_list.py` – listowanie katalogów  

### 🌐 Web / Playwright
- `web_fetch.py` – pobieranie stron przez Playwright  
- `browser_mode.py` – „tryb przeglądarkowy”  
- `browser_query.py` – sterowanie i analiza stron  

### 📡 Integracja sprzętowa
- `mqtt.py` – obsługa MQTT (spec + invoke)  
- `shelly_mqtt_listener.py` – słuchacz zmian urządzeń Shelly  

### 🔧 Registry
- `registry.py` – rejestracja narzędzi i mapowanie nazw na funkcje

Dzięki temu agent może, przez tool-calle, wykonywać realne akcje w systemie.

---

## 5. Warstwa sprzętowa (Hardware bridge)

Za komendy typu:

- „włącz światło 1”
- „mrugnij dwa razy czerwonym”
- „sprawdź stan Shelly”

odpowiada:

- **modules/hardware_bridge.py** – tłumaczy intencje na komendy MQTT/Shelly.  
- **mqtt.py + shelly_mqtt_listener.py** – aktualizacja stanu urządzeń.

Agent nie działa na ślepo — zna aktualny stan świata (światła, czujniki itd.).

---

## 6. Warstwa bezpieczeństwa (Guardrails)

Aby agent nie wykonał szkodliwych komend:

- **modules/guardrails.py****:**
  - filtruje komendy systemowe,
  - blokuje niebezpieczne operacje,
  - chroni pliki i środowisko.

W połączeniu z `metrics` i `self_heal` daje to stabilną, odporną na błędy architekturę.

---

## 7. Warstwa komunikacji i rozszerzeń

### 🛰 HalBridge server  
`halbridge_server.py`  
Zapewnia API do integracji:

- przeglądarkowego rozszerzenia HalBridge,
- lokalnego terminala,
- innych programów.

### 🔌 modules/bus.py  
Prosty event bus do komunikacji między modułami.

---

## 8. Pełny przepływ działania (od wpisania polecenia)

1. Użytkownik wpisuje tekst.  
2. `gpt_chat_v3.py` klasyfikuje wejście:  
   - lokalna komenda?  
   - alias?  
   - tool-call?  
   - intencja?  
   - zwykły tekst?  
3. Jeśli to tekst → idzie do LLM.  
4. Jeśli to intencja →  
   - recognizer → extract_slots → router.  
5. Router wybiera moduł (web, pliki, sprzet, etc.).  
6. Narzędzie wykonuje zadanie.  
7. Wynik jest analizowany (`metrics`, `result_analyzer`).  
8. Agent generuje odpowiedź.  

---

## 9. Najważniejsze fakty w skrócie

- `gpt_chat_v3.py` to **centralny mózg** HalBridge.  
- Spina wszystkie moduły: web, pliki, sprzęt, code, bezpieczeństwo.  
- Pozwala modelowi wykonywać prawdziwe komendy systemowe.  
- Dzięki Intent Engine rozumie, co chcesz zrobić.  
- Jest autentycznym „asystentem operacyjnym”, a nie samym chatem.

---

# HalBridge – Web Automation & AI Integration

HalBridge to modułowy system asystenta AI działający w terminalu, rozszerzony o funkcje web automation, sterowanie urządzeniami, analizę danych oraz wykonywanie komend systemowych.  
System wykorzystuje Playwrighta, własną logikę analizy tekstu oraz dynamiczną interpretację komend użytkownika.

---

## 1. Architektura modułu Web / Playwright

Moduł webowy HalBridge umożliwia:

- otwieranie stron internetowych,
- renderowanie stron w prawdziwej przeglądarce (Chromium headless),
- ekstrakcję czytelnego tekstu przez Readability,
- interpretację poleceń typu „otwórz onet” lub „poszukaj newsów”,
- automatyczne translacje języka naturalnego na URL,
- przygotowanie zawartości stron dla modułów analizy.

Moduł składa się z sześciu kluczowych plików.

---

## 2. Pliki modułu web

### **hal_webfetch.py**
Najważniejszy element systemu. Odpowiada za:

- uruchomienie Playwright (Chromium) w trybie headless,
- załadowanie strony z pełnym JavaScriptem,
- pobranie HTML po pełnym renderowaniu,
- przetworzenie tekstu przez „readability”,
- zwrócenie czystego tekstu.

Używany jako zewnętrzny proces.

---

### **modules/tools/web_fetch.py**
Warstwa API dla agenta.  
Uruchamia `hal_webfetch.py` w osobnym Pythonie (z venv), a następnie:

- pobiera output,
- zwraca wynik jako słownik JSON,
- obsługuje błędy subprocessów,
- zawiera funkcję `resolve_natural_query()`, która tłumaczy komendy na URL:
  - „otwórz onet” → `https://onet.pl`
  - „pokaż stronę wp.pl” → `https://wp.pl`
  - „poszukaj laptopów” → bing search URL

---

### **modules/web_bridge_copy.py**
Minimalistyczny wrapper.  
Zawiera:

- funkcję `fetch_url(url)` – niskopoziomowy fetcher,
- `web_fetch(url)` – główna fasada rejestrowana w narzędziach.

---

### **browser_helper.py**
Lekka wersja fetchera dla debugowania.  
Zwraca:

- tytuł strony (`page.title()`),
- treść `<body>` (przyciętą do 8 KB).

---

### **browser_controller.py**
Warstwa sterowania przeglądarką poprzez osobny worker:

- „open” – otwarcie strony,
- „click_result” – kliknięcie linku w wynikach,
- „back”, „refresh” – przyszłe funkcje nawigacyjne.

---

### **command_mapper_browser.json**
Mapa komend języka naturalnego:

```json
{
  "otwórz": "open",
  "klik": "click_result",
  "wstecz": "back",
  "odśwież": "refresh"
}

Umożliwia agentowi obsługę komend mówionych.


---

3. Dlaczego Playwright?

Zwykłe żądania HTTP pobierają surowy HTML.
HalBridge potrzebuje:

wykonania JavaScript,

dynamicznego DOM,

ładowania SPA,

pełnego tekstu widocznego w przeglądarce.


Dlatego Playwright + Chromium headless jest kluczowy.


---

4. Instalacja środowiska (zalecane)

python3 -m venv .venv_playwright
source .venv_playwright/bin/activate
pip install playwright readability-lxml
playwright install


---

5. Odpalanie web_fetch

python modules/tools/web_fetch.py

lub przez agenta:

otwórz onet
szukaj espresso machine ranking
pokaż stronę wp.pl


---

6. Struktura modułu

hal_webfetch.py
modules/
 ├ tools/
 │   └ web_fetch.py
 ├ web_bridge_copy.py
browser_helper.py
browser_controller.py
command_mapper_browser.json


---

7. Status projektu

Moduł działa stabilnie w środowisku headless.
Planowane:

klikanie linków,

interaktywne przeglądanie stron,

integracja z systemem poleceń agenta,

automatyczne streszczenia stron.
