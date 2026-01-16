#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ekstrakcja WYDATKÓW z maili Inteligo/PKO tylko na podstawie e-maili. Zasady:

Bierzemy tylko wiadomości z danego miesiąca.
W treści musi wystąpić fraza "OBCIĄŻENIE" (również bez polskich znaków).
Wydatek to pierwsza w kolejności kwota z walutą (PLN/zł) ze znakiem minus.
Ignorujemy linie zawierające saldo/dostępne środki.
Jedna wiadomość -> maksymalnie jedna kwota (brak dublowania powtórzeń w tekście).

Wyjście: 
@#@MODEL_WYDATKI@#@ 
@#@SUMA_WYDATKI@#@ 
@#@SZCZEGÓŁY_WYDATKI@#@ 
@#@KONIEC@#@
"""

import os
import re
import sys
import json
import base64
import datetime
from collections import defaultdict
from email.utils import parseaddr

from bs4 import BeautifulSoup
from html2text import html2text

from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# =============================================================================
# KONFIGURACJA
# =============================================================================

CONF = os.path.expanduser("~/.config/gmail_bridge")
CREDS_JSON = os.path.join(CONF, "client_secret.json")
TOKEN_JSON = os.path.join(CONF, "token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# =============================================================================
# WZORCE I SŁOWA-KLUCZE
# =============================================================================

AMOUNT_NEG_CURR_RE = re.compile(r"-\s*(\d[\d\s\u00A0]{0,12}(?:[.,]\d{2}))\s*(?:zł|PLN)\b", re.I)
BALANCE_WORDS = ("saldo", "dostępne", "dostepne", "stan konta", "dostępnych", "dostepnych")

# =============================================================================
# NARZĘDZIA POMOCNICZE
# =============================================================================

def _normalize_text(text):
    """Normalizuje tekst poprzez zamianę NBSP na spację i unifikację minusa"""
    return text.replace("\xa0", " ").replace("\u2212", "-")

# =============================================================================
# OPERACJE GMAIL API
# =============================================================================

def load_service():
    """Inicjalizuje serwis Gmail API"""
    os.makedirs(CONF, exist_ok=True)
    creds = None
    
    if os.path.exists(TOKEN_JSON):
        creds = Credentials.from_authorized_user_file(TOKEN_JSON, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_JSON):
                print("@#@Brak pliku client_secret.json w ~/.config/gmail_bridge@#@")
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_JSON, SCOPES)
            creds = flow.run_console()
            with open(TOKEN_JSON, "w") as f:
                f.write(creds.to_json())
                
    return build("gmail", "v1", credentials=creds)

def gmail_list_all_ids(svc, query, max_per_page=500):
    """Pobiera wszystkie ID wiadomości dla zapytania"""
    ids = []
    token = None
    
    while True:
        res = svc.users().messages().list(
            userId="me", q=query, maxResults=max_per_page, pageToken=token
        ).execute()
        
        for it in res.get("messages", []) or []:
            ids.append(it["id"])
            
        token = res.get("nextPageToken")
        if not token:
            break
            
    return ids

def read_messages(svc, ids):
    """Pobiera pełne treści wiadomości na podstawie listy ID"""
    out = {}
    for mid in ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        out[mid] = msg
    return out

# =============================================================================
# PRZETWARZANIE WIADOMOŚCI
# =============================================================================

def _header(msg, name):
    """Wyodrębnia wartość nagłówka wiadomości"""
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""

def _msg_text(msg):
    """Wyodrębnia tekst z wiadomości email"""
    payload = msg.get("payload", {})

    def walk(p):
        if "data" in p.get("body", {}) and p.get("mimeType", "").startswith("text/"):
            raw = base64.urlsafe_b64decode(p["body"]["data"]).decode(errors="ignore")
            if p.get("mimeType") == "text/html":
                try:
                    txt = html2text(raw)
                except Exception:
                    txt = BeautifulSoup(raw, "html.parser").get_text(" ")
                return _normalize_text(txt)
            return _normalize_text(raw)
            
        for part in p.get("parts", []) or []:
            t = walk(part)
            if t:
                return t
                
        return ""

    return walk(payload) or _normalize_text(msg.get("snippet") or "")

def _ym_from_ts(ts_ms):
    """Konwertuje znacznik czasu na format Rok-Miesiąc"""
    dt = datetime.datetime.fromtimestamp(int(ts_ms) / 1000)
    return dt.strftime("%Y-%m")

# =============================================================================
# BUDOWA ZAPYTAŃ
# =============================================================================

def build_month_dates(month_ym):
    """Tworzy ciąg zapytania z zakresem dat dla danego miesiąca"""
    y, m = month_ym.split("-")
    if m != "12":
        return f'after:{y}/{m}/01 before:{y}/{int(m)+1:02d}/01'
    return f'after:{y}/12/01 before:{int(y)+1}/01/01'

def build_query(month_ym):
    """Tworzy zapytanie dla wiadomości bankowych"""
    dates = build_month_dates(month_ym)
    return f'{dates} (from:inteligo.pl OR from:pkobp.pl)'

# =============================================================================
# EKSTRAKCJA WYDATKÓW
# =============================================================================

def _has_obciazenie(text_low):
    """Sprawdza, czy tekst zawiera frazę OBCIĄŻENIE (w różnych wariantach)"""
    return ("obciążenie" in text_low) or ("obciazenie" in text_low) or ("obciażenie" in text_low)

def extract_expense_amount_from_text(text):
    """Wyodrębnia kwotę wydatku z tekstu wiadomości"""
    # Warunek: musi wystąpić OBCIĄŻENIE (również bez PL znaków)
    low_all = text.lower()
    if not _has_obciazenie(low_all):
        return None

    # Szukamy pierwszej linii z ujemną kwotą i walutą, ignorując linie z saldem
    for ln in text.splitlines():
        low = ln.lower()
        if any(w in low for w in BALANCE_WORDS):
            continue
            
        m = AMOUNT_NEG_CURR_RE.search(ln)
        if m:
            try:
                val = float(m.group(1).replace(" ", "").replace(",", "."))
                return round(abs(val), 2)
            except ValueError:
                continue
                
    return None

# =============================================================================
# OBSŁUGA ARGUMENTÓW WIERSZA POLECEŃ
# =============================================================================

def parse_args(argv):
    """Parsuje argumenty wiersza poleceń"""
    month = None
    i = 0
    
    while i < len(argv):
        if argv[i] == "--month":
            month = argv[i + 1]
            i += 2
        else:
            i += 1
            
    if not month:
        month = datetime.datetime.now().strftime("%Y-%m")
        
    return month

# =============================================================================
# FUNKCJA GŁÓWNA
# =============================================================================

def main():
    """Główna funkcja przetwarzająca wiadomości i generująca raporty"""
    month = parse_args(sys.argv[1:])
    svc = load_service()

    q = build_query(month)
    ids = gmail_list_all_ids(svc, q, max_per_page=500)
    msgs = read_messages(svc, ids)

    matched = []
    sum_by_month = defaultdict(float)

    for mid, m in msgs.items():
        subj = _header(m, "Subject") or ""
        text = subj + "\n" + _msg_text(m)
        amt = extract_expense_amount_from_text(text)
        
        if amt is not None:
            ym = _ym_from_ts(m.get("internalDate", "0"))
            sum_by_month[ym] += amt
            matched.append({
                "id": mid, 
                "amount": amt, 
                "subject": subj
            })

    # Przygotowanie modelu
    model = {
        "rule": {
            "must_contain": "OBCIĄŻENIE",
            "amount_pattern": "^-<kwota> (PLN|zł) w tej samej linii",
            "ignore_lines_with": list(BALANCE_WORDS),
            "dedup_per_message": True,
        }
    }

    # Zapis wyników
    out_dir = os.path.expanduser("~/HALbridge/modules/gmail_bridge")
    os.makedirs(out_dir, exist_ok=True)
    
    with open(os.path.join(out_dir, "expense_obciazenie_matched.json"), "w", encoding="utf-8") as f:
        json.dump(matched, f, ensure_ascii=False, indent=2)
        
    with open(os.path.join(out_dir, "expense_obciazenie_model.json"), "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    # Wyświetlenie wyników
    print("@#@MODEL_WYDATKI@#@")
    print(json.dumps(model, ensure_ascii=False, indent=2))
    
    print("@#@SUMA_WYDATKI@#@")
    for ym in sorted(sum_by_month.keys()):
        print(f"{ym}  {sum_by_month[ym]:.2f} zł")
        
    print("@#@SZCZEGÓŁY_WYDATKI@#@")
    for tr in matched:
        print(f'{tr["subject"]}: {tr["amount"]:.2f} zł')
        
    print("@#@KONIEC@#@")

if __name__ == "__main__":
    main()
