gpt_chat_v3.py to jest głowny plik systemu 

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
