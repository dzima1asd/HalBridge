#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Skrypt: Wyodrębnianie wpływów z maili Inteligo w zadanym miesiącu.
- Uczy się po znanych kwotach (szuka ID wiadomości zawierających wskazane kwoty).
- Zapisuje model (dla wglądu), ale do finalnej ekstrakcji używa stabilnych reguł Inteligo.
- Wypisuje MODEL, SUMA (per miesiąc) i SZCZEGÓŁY w formacie z @#@...@#@, jak w poprzednich narzędziach.

Użycie:
  python3 income_inteligo.py --month 2025-08 --learn-from-amounts "1856.00,2700.00,630.00"
  (parametry opcjonalne)
"""

import os
import re
import sys
import json
import base64
import datetime
from collections import defaultdict, Counter
from email.utils import parseaddr

from bs4 import BeautifulSoup
from html2text import html2text

from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
try:
    from modules.bus import BUS
except Exception:
    BUS = None

# --- Konfiguracja OAuth/Gmail API ---
CONF = os.path.expanduser("~/.config/gmail_bridge")
CREDS_JSON = os.path.join(CONF, "client_secret.json")
TOKEN_JSON = os.path.join(CONF, "token.json")
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# --- Stabilne reguły dla maili Inteligo (jak w pierwszym programie) ---
INTELIGO_RULES = {
    "require_sender": "inteligo@inteligo.pl",
    "require_subject_contains": "Wiadomość z Inteligo",
    "require_keywords_any": [
        "UZNANIE",
        "PRZELEW PRZYCH",
        "PRZELEW PRZYCHODZĄCY",
        "POS ZWROT",
        "REKLAMACJA KARTOWA",
    ],
    "forbid_keywords_any": [
        "wyciąg okresowy",
        "kapitał zakładowy",
    ],
    "accept_first_plus_amount_before": "Data waluty",
}

# Kwoty typu: +1 234,56 zł | 1 234,56 PLN | -12.00 | 12.00 itp.
AMOUNT_RE = re.compile(
    r"([+-]?\d[\d\s\u00A0]{0,12}(?:[.,]\d{2})?)[\s\u00A0]*(?:zł|PLN)?\b",
    re.I,
)


# =========================
# Gmail: autoryzacja i I/O
# =========================
def load_service():
    """Zwraca obiekt usługi Gmail API (v1)."""
    os.makedirs(CONF, exist_ok=True)
    creds = None

    # Wczytaj istniejący token (jeśli jest)
    if os.path.exists(TOKEN_JSON):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_JSON, SCOPES)
        except Exception:
            creds = None

    # Jeśli nie ma lub jest nieważny — wymuś nową autoryzację
    if not creds or not creds.valid:
        print("🔑 Token Gmaila nieaktywny lub wygasł. Uruchamiam nowy flow OAuth...")
        if not os.path.exists(CREDS_JSON):
            print("@#@Brak pliku client_secret.json w ~/.config/gmail_bridge@#@")
            sys.exit(1)

        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_JSON, SCOPES)
        creds = flow.run_console()  # ⬅️ Wymuszone logowanie w konsoli

        # Zapisz nowy token
        with open(TOKEN_JSON, "w") as f:
            f.write(creds.to_json())

        print("✅ Nowy token Gmail zapisany:", TOKEN_JSON)

    return build("gmail", "v1", credentials=creds)


def gmail_list_all_ids(svc, query, max_per_page=500):
    """Zwraca wszystkie ID wiadomości dla danego zapytania Gmail (z paginacją)."""
    ids = []
    token = None
    while True:
        req = svc.users().messages().list(
            userId="me", q=query, maxResults=max_per_page, pageToken=token
        )
        res = req.execute()
        for it in res.get("messages", []) or []:
            ids.append(it["id"])
        token = res.get("nextPageToken")
        if not token:
            break
    return ids


def read_messages(svc, ids):
    """Pobiera pełne treści wiadomości po ID."""
    out = {}
    for mid in ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        out[mid] = msg
    return out


# =========================
# Parsowanie treści wiadomości
# =========================
def _header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _msg_text(msg):
    """Zwraca zrekonstruowany tekst wiadomości (HTML->txt lub plain)."""
    payload = msg.get("payload", {})

    def walk(p):
        if "data" in p.get("body", {}) and p.get("mimeType", "").startswith("text/"):
            raw = base64.urlsafe_b64decode(p["body"]["data"]).decode(errors="ignore")
            if p.get("mimeType") == "text/html":
                try:
                    return html2text(raw)
                except Exception:
                    return BeautifulSoup(raw, "html.parser").get_text(" ")
            return raw

        for part in p.get("parts", []) or []:
            t = walk(part)
            if t:
                return t
        return ""

    return walk(payload) or (msg.get("snippet") or "")


# =========================
# Narzędzia kwot i dat
# =========================
def _amounts(text):
    vals = []
    for m in AMOUNT_RE.finditer(text):
        s = (
            m.group(1)
            .replace("\xa0", "")
            .replace(" ", "")
            .replace(",", ".")
            .replace("+", "")
        )
        try:
            vals.append(float(s))
        except ValueError:
            pass
    return vals

def classify_entry(subj, body):
    """Klasyfikacja na podstawie treści maila (z normalizacją znaków)."""
    import unicodedata
    def _norm(s:str)->str:
        s = s.lower()
        s = unicodedata.normalize('NFKD', s)
        return ''.join(ch for ch in s if not unicodedata.combining(ch))
    text = _norm(f"{subj}\n{body}")

    atm_kw    = ("bankomat","atm","wyplata z bankomatu","wplatomat")
    phone_kw  = ("przelew na telefon","blik na telefon","blik p2p")
    fuel_kw   = ("orlen","shell","circle k","bp","moya","lotos","amic","avia","total")
    income_kw = ("wplyw","uznanie","zasilenie","przelew przychodzacy","pos zwrot","reklamacja kartowa")
    card_kw   = ("autoryzacja transakcji kartowej","transakcja kartowa","transakcja karta",
                 "platnosc karta","platnosc","obciazenie","visa","mastercard")

    if any(k in text for k in atm_kw): return "atm"
    if any(k in text for k in phone_kw): return "phone_transfer"
    if any(k in text for k in fuel_kw): return "fuel"
    if any(k in text for k in income_kw): return "income"
    if any(k in text for k in card_kw): return "card"
    return "unknown"
def _ym_from_ts(ts_ms):
    dt = datetime.datetime.fromtimestamp(int(ts_ms) / 1000)
    return dt.strftime("%Y-%m")


def _variants_pl(amount):
    """Warianty zapisu kwoty spotykane w mailach bankowych."""
    s = f"{amount:.2f}"
    s_dot = s
    s_com = s.replace(".", ",")
    int_part, dec = s.split(".")
    with_space = f"{int(int_part):,}".replace(",", " ")
    s_spc_com = f"{with_space},{dec}"
    return [s_com, s_dot, s_spc_com]


# =========================
# Wyszukiwanie po znanych kwotach
# =========================
def search_ids_for_amounts(svc, amounts, month_ym):
    """Dla podanych kwot buduje OR-zapytania i znajduje ID wiadomości w danym miesiącu."""
    y, m = month_ym.split("-")
    if m != "12":
        q_dates = f'after:{y}/{m}/01 before:{y}/{int(m)+1:02d}/01'
    else:
        q_dates = f'after:{y}/12/01 before:{int(y)+1}/01/01'

    ids = set()
    per_amount_hits = defaultdict(list)

    for a in amounts:
        variants = _variants_pl(a)
        clauses = " OR ".join([f'"{v}"' for v in variants])
        query = f"{q_dates} {clauses}"
        found_ids = gmail_list_all_ids(svc, query)
        for mid in found_ids:
            ids.add(mid)
            per_amount_hits[a].append(mid)

    return list(ids), per_amount_hits


# =========================
# Ekstrakcja cech do wglądu/analizy
# =========================
def extract_features(msg, known_amounts=None):
    from_val = _header(msg, "From") or ""
    subj = _header(msg, "Subject") or ""
    body = _msg_text(msg)
    text = subj + "\n" + body

    feats = {
        "sender_email": parseaddr(from_val)[1].lower(),
        "sender_name": parseaddr(from_val)[0],
        "subject": subj,
        "has_kw_inteligo_pow": "inteligo powiadomienia" in text.lower(),
        "has_kw_uznanie": "uznanie" in text.lower(),
        "has_kw_przych": ("przych" in text.lower()) or ("przychodząc" in text.lower()),
        "has_kw_data_waluty": "data waluty" in text.lower(),
        "has_kw_dostepne": "dostępne" in text.lower(),
        "has_kw_wyciag": "wyciąg okresowy" in text.lower(),
        "has_kw_kapital": "kapitał zakładowy" in text.lower(),
    }

    amts = _amounts(text)
    feats["n_amounts"] = len(amts)
    feats["max_amount_abs"] = max([abs(x) for x in amts], default=0.0)

    pos_amount_lines = []
    for line in text.splitlines():
        if "pln" in line.lower():
            m = re.search(
                r"\+\s*\d[\d\s\u00A0]*(?:[.,]\d{2})?\s*(?:zł|PLN)?", line, re.I
            )
            if m:
                pos_amount_lines.append(line.strip())

    feats["pos_amount_lines"] = pos_amount_lines
    feats["matches_known"] = []

    if known_amounts:
        norm_text = text.replace("\xa0", " ")
        for a in known_amounts:
            for v in _variants_pl(a):
                if v in norm_text or ("+" + v) in norm_text:
                    feats["matches_known"].append(a)
                    break

    return feats


# =========================
# Model podglądowy (diagnoza)
# =========================
def learn_model(features_list):
    """Zwraca statystyki ze zbioru trafień, ale do liczenia używamy stabilnych reguł."""
    hits = [f for f in features_list if f["matches_known"]]
    senders = Counter(f["sender_email"] for f in hits)
    subjects = Counter(f["subject"] for f in hits)

    k_bools = Counter(
        {
            "has_kw_inteligo_pow": sum(1 for f in hits if f["has_kw_inteligo_pow"]),
            "has_kw_uznanie": sum(1 for f in hits if f["has_kw_uznanie"]),
            "has_kw_przych": sum(1 for f in hits if f["has_kw_przych"]),
            "has_kw_data_waluty": sum(1 for f in hits if f["has_kw_data_waluty"]),
            "has_kw_dostepne": sum(1 for f in hits if f["has_kw_dostepne"]),
            "has_kw_wyciag": sum(1 for f in hits if f["has_kw_wyciag"]),
            "has_kw_kapital": sum(1 for f in hits if f["has_kw_kapital"]),
        }
    )

    model = {
        "top_sender": senders.most_common(1)[0][0] if senders else "",
        "subject_whitelist": [s for s, c in subjects.most_common() if c >= 1],
        "bool_supports": dict(k_bools),
        "rule": {
            # Do finalnego liczenia używamy poniższych stabilnych reguł Inteligo:
            "require_sender": "inteligo@inteligo.pl",
            "require_subject_contains": "Wiadomość z Inteligo",
            "require_keywords_any": [
                "UZNANIE",
                "PRZELEW PRZYCH",
                "PRZELEW PRZYCHODZĄCY",
                "POS ZWROT",
                "REKLAMACJA KARTOWA",
            ],
            "forbid_keywords_any": [
                "wyciąg okresowy",
                "kapitał zakładowy",
            ],
            "accept_first_plus_amount_before": "Data waluty",
        },
    }
    return model


# =========================
# Ekstrakcja kwoty z powiadomień Inteligo (stabilne reguły)
# =========================
def extract_amount_from_inteligo(msg):
    subj = _header(msg, "Subject") or ""
    from_addr = parseaddr(_header(msg, "From"))[1].lower()
    body = _msg_text(msg)
    text = subj + "\n" + body

    # Nadawca
    if INTELIGO_RULES["require_sender"] and from_addr != INTELIGO_RULES["require_sender"]:
        return None

    # Temat
    if INTELIGO_RULES["require_subject_contains"].lower() not in subj.lower():
        return None

    # Zabronione słowa
    for bad in INTELIGO_RULES["forbid_keywords_any"]:
        if bad.lower() in text.lower():
            return None

    # Wymagane słowa (którekolwiek)
    if not any(k.lower() in text.lower() for k in INTELIGO_RULES["require_keywords_any"]):
        return None

    # Bierzemy fragment przed "Data waluty"
    section = text.split(INTELIGO_RULES["accept_first_plus_amount_before"])[0]

    # Preferujemy linie z plusem
    plus_lines = [ln for ln in section.splitlines() if "+" in ln]
    for ln in plus_lines:
        m = re.search(r"\+\s*(\d[\d\s\u00A0]*(?:[.,]\d{2})?)\s*(?:zł|PLN)?", ln, re.I)
        if m:
            s = m.group(1).replace("\xa0", "").replace(" ", "").replace(",", ".")
            try:
                val = float(s)
                return max(val, 0.0)
            except ValueError:
                pass

    # Fallback: każda dodatnia kwota w sekcji
    amts = _amounts(section)
    pos = [a for a in amts if a > 0]
    return max(pos) if pos else None


# =========================
# Zastosowanie reguł (abstrakcja)
# =========================
def apply_learned_rule(msg, model):
    """Dla spójności interfejsu: używamy stabilnych reguł Inteligo."""
    return extract_amount_from_inteligo(msg)


# =========================
# Główna ścieżka
# =========================
def build_month_query(month_ym, sender, subject_contains):
    """Buduje zapytanie Gmail ograniczone do miesiąca i filtru nadawcy/tematu."""
    y, m = month_ym.split("-")
    if m != "12":
        q_dates = f'after:{y}/{m}/01 before:{y}/{int(m)+1:02d}/01'
    else:
        q_dates = f'after:{y}/12/01 before:{int(y)+1}/01/01'
    sender = sender or "inteligo@inteligo.pl"
    subject_contains = subject_contains or "Wiadomość z Inteligo"
    q_all = f'{q_dates} from:{sender} "{subject_contains}"'
    return q_all


def parse_args(argv):
    month = None
    learn_amounts = []
    print_sum = True

    i = 0
    while i < len(argv):
        if argv[i] == "--month":
            month = argv[i + 1]
            i += 2
        elif argv[i] == "--learn-from-amounts":
            learn_amounts = [
                float(x) for x in argv[i + 1].replace(" ", "").split(",") if x
            ]
            i += 2
        elif argv[i] == "--no-print-sum":
            print_sum = False
            i += 1
        else:
            i += 1

    if not month:
        now = datetime.datetime.now()
        month = now.strftime("%Y-%m")

    return month, learn_amounts, print_sum


def main():
    month, learn_amounts, print_sum = parse_args(sys.argv[1:])
    svc = load_service()

    # 1) Szukanie ID wiadomości zawierających znane kwoty (do analizy modelu)
    ids, per_amount = search_ids_for_amounts(svc, learn_amounts, month)
    msgs = read_messages(svc, ids)

    # 2) Cechy i "model" diagnostyczny
    feats = []
    for mid, m in msgs.items():
        f = extract_features(m, known_amounts=learn_amounts)
        f["id"] = mid
        f["ym"] = _ym_from_ts(m.get("internalDate", "0"))
        feats.append(f)

    model = learn_model(feats)

    # 3) Zapis modelu i wyników
    out_dir = os.path.expanduser("~/HALbridge/modules/gmail_bridge")
    os.makedirs(out_dir, exist_ok=True)

    model_path = os.path.join(out_dir, "income_model.json")
    with open(model_path, "w", encoding="utf-8") as f:
        json.dump(model, f, ensure_ascii=False, indent=2)

    # 4) Pobieramy wszystkie wiadomości Inteligo w danym miesiącu
    q_all = build_month_query(
        month_ym=month,
        sender=model["rule"]["require_sender"],
        subject_contains=model["rule"]["require_subject_contains"],
    )
    all_ids = gmail_list_all_ids(svc, q_all, max_per_page=500)
    all_msgs = read_messages(svc, all_ids)

    # 5) Ekstrakcja stabilnymi regułami
    sum_by_month = defaultdict(float)
    matched_list = []

    for mid, m in all_msgs.items():
        amt = apply_learned_rule(m, model)
        if amt:
            ym = _ym_from_ts(m.get("internalDate", "0"))
            sum_by_month[ym] += round(amt, 2)
            matched_list.append(
                {
                    "id": mid,
                    "amount": round(amt, 2),
                    "subject": _header(m, "Subject"),
                }
            )

    with open(os.path.join(out_dir, "income_matched.json"), "w", encoding="utf-8") as f:
        json.dump(matched_list, f, ensure_ascii=False, indent=2)

    # 6) Wyjście w formacie zgodnym z poprzednimi narzędziami
    print("@#@MODEL@#@")
    print(json.dumps(model, ensure_ascii=False, indent=2))
    print("@#@SUMA@#@")
    if print_sum:
        for ym in sorted(sum_by_month.keys()):
            print(f"{ym}  {sum_by_month[ym]:.2f} zł")

    print("@#@SZCZEGÓŁY@#@")
    for tr in matched_list:
        print(f'{tr["subject"]}: {tr["amount"]:.2f} zł')

    print("@#@KONIEC@#@")


if __name__ == "__main__":
    main()
