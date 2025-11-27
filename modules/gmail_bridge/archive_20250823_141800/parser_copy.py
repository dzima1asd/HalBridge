#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
html_to_transactions.py
Parser wyciągów HTML (Inteligo/PKO + forwardy) do bazy SQLite.

Tworzy tabelę `transactions` o polach:
- ym                (YYYY-MM)
- op_date           (YYYY-MM-DD; gdy jest czas: op_datetime)
- op_datetime       (ISO 'YYYY-MM-DDTHH:MM:SS' jeśli uda się znaleźć)
- value_date        (YYYY-MM-DD, 'Data waluty')
- direction         ('debet' lub 'kredyt')
- amount            (REAL; ujemne dla debetu, dodatnie dla kredytu)
- currency          (np. 'PLN')
- title             (tytuł przelewu / opis operacji)
- counterparty      (odbiorca dla debetu / nadawca dla kredytu)
- location          (np. miasto/terminal)
- address           (np. URL lub adres)
- reference_no      (numer referencyjny)
- phone             (np. +48 ...)
- source_file       (pełna ścieżka do HTML-a)
- row_hash          (unikalny hash wiersza)
"""

from __future__ import annotations
import argparse
import datetime
import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup

DB_PATH = Path("~/.local/share/bankdb/bank.db").expanduser()

DDL = """
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ym TEXT,
  op_date TEXT,
  op_datetime TEXT,
  value_date TEXT,
  direction TEXT CHECK(direction IN ('debet','kredyt')),
  amount REAL,
  currency TEXT,
  title TEXT,
  counterparty TEXT,
  location TEXT,
  address TEXT,
  reference_no TEXT,
  phone TEXT,
  source_file TEXT,
  row_hash TEXT UNIQUE,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_tx_ym ON transactions(ym);
CREATE INDEX IF NOT EXISTS idx_tx_opdate ON transactions(op_date);
CREATE INDEX IF NOT EXISTS idx_tx_counterparty ON transactions(counterparty);
"""

# ------ Regexy i słowa-klucze ------

AMOUNT_RE = re.compile(
    r'(?P<sign>[-+−]?)\s*(?P<int>\d[\d\s\u00A0]{0,12})(?P<dec>[.,]\d{2})?\s*(?P<cur>PLN|zł)?\b',
    re.I,
)
# daty
DATE_ISO_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
DATETIME_ISO_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?\b')
DATE_DOT_RE = re.compile(r'\b(\d{2})[.\-\/](\d{2})[.\-\/](\d{4})\b')
TIME_RE = re.compile(r'\b(\d{2}):(\d{2})(?::(\d{2}))?\b')

# etykiety pól
LAB_TITLE = ('tytuł', 'tytul', 'opis', 'nazwa operacji', 'szczegóły', 'szczegoly')
LAB_VALUE_DATE = ('data waluty',)
LAB_EXEC_DATE = ('data wykonania', 'data transakcji', 'czas operacji')
LAB_COUNTERPARTY_IN = ('nadawca', 'zleceniodawca', 'od')
LAB_COUNTERPARTY_OUT = ('odbiorca', 'adresat', 'do', 'sprzedawca', 'merchant')
LAB_LOCATION = ('lokalizacja',)
LAB_ADDRESS = ('adres', 'www')
LAB_REFNO = ('numer referencyjny', 'nr referencyjny', 'reference', 'ref')
LAB_PHONE = ('numer telefonu', 'telefon', 'phone')

# klasyfikatory
EXPENSE_TERMS = (
    'obciąż', 'obciaz', 'obciąz', 'przelew wych', 'wychodząc', 'wychodzacy', 'wykonany',
    'wypłata', 'wyplata', 'płatno', 'platno', 'transakcja kart', 'operacja kart',
    'blik', 'pos', 'zakup', 'opłata', 'prowizja'
)
INCOME_TERMS = (
    'uznanie', 'przelew przych', 'przychodząc', 'przychodzacy', 'wpływ', 'wplyw',
    'pos zwrot', 'zwrot', 'reklamac'
)

BALANCE_WORDS = ('saldo', 'dostępne', 'dostepne', 'stan konta', 'dostępnych', 'dostepnych')


# ------ Narzędzia ------

def normalize_spaces(s: str) -> str:
    return " ".join((s or "").replace("\u00A0", " ").split())

def to_float_amount(m: re.Match) -> Optional[float]:
    sign = m.group('sign') or ''
    iv = (m.group('int') or '').replace(' ', '').replace('\u00A0', '')
    dv = (m.group('dec') or '').replace(',', '.')
    txt = f"{iv}{dv}"
    if not txt:
        return None
    try:
        val = float(txt)
    except ValueError:
        return None
    if sign in ('-', '−'):
        val = -val
    return val

def pick_currency(text: str) -> str:
    return 'PLN' if re.search(r'\b(PLN|zł)\b', text, re.I) else 'PLN'

def parse_any_date(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Zwraca (date, datetime_iso) jeśli da się wyłuskać konkretną datę/czas."""
    text = text.strip()
    mdt = DATETIME_ISO_RE.search(text)
    if mdt:
        y, mo, d, hh, mm, ss = mdt.groups()
        ss = ss or '00'
        dt_iso = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}T{int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
        return dt_iso[:10], dt_iso
    m = DATE_ISO_RE.search(text)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", None
    m = DATE_DOT_RE.search(text)
    if m:
        d, mo, y = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}", None
    return None, None

def month_from_date(date: str) -> str:
    return date[:7]

def guess_direction(amount: float, blob: str) -> str:
    t = blob.lower()
    if amount < 0:
        return 'debet'
    if amount > 0:
        return 'kredyt'
    # amount == 0: spróbuj po słowach
    if any(k in t for k in EXPENSE_TERMS):
        return 'debet'
    if any(k in t for k in INCOME_TERMS):
        return 'kredyt'
    return 'kredyt'  # domyślnie optymistycznie...

def find_label_value(blob: str, labels: Iterable[str]) -> Optional[str]:
    t = blob.lower()
    for lab in labels:
        i = t.find(lab + ':')
        if i == -1:
            i = t.find(lab + ' :')
        if i != -1:
            frag = blob[i:].split('\n', 1)[0]
            # po dwukropku do końca linii
            v = frag.split(':', 1)[-1].strip()
            return normalize_spaces(v)[:240]
    return None

def compute_row_hash(source_file: Path, op_date: str, amount: float, title: str) -> str:
    base = f"{source_file}|{op_date}|{amount:.2f}|{title[:80]}"
    return hashlib.sha256(base.encode('utf-8', 'ignore')).hexdigest()


# ------ Parsowanie pojedynczego pliku ------

def extract_transactions_from_html(path: Path) -> List[Dict]:
    html = path.read_text(encoding='utf-8', errors='ignore')
    soup = BeautifulSoup(html, 'html.parser')

    # 1) Wyciągnij wszystkie blokowe linie tekstu
    blocks: List[str] = []

    # typowo transakcje siedzą w tabelach:
    for tr in soup.find_all('tr'):
        cells = [normalize_spaces(td.get_text(" ")) for td in tr.find_all(['td','th'])]
        line = normalize_spaces(" | ".join([c for c in cells if c]))
        if line:
            blocks.append(line)

    # dołóż akapity
    for tag in soup.find_all(['p', 'li', 'div']):
        txt = normalize_spaces(tag.get_text(" "))
        if txt:
            blocks.append(txt)

    # usuń ewidentne linie salda
    clean_blocks = [b for b in blocks if not any(w in b.lower() for w in BALANCE_WORDS)]

    # 2) Dla każdej linii z kwotą zbuduj rekord
    txs: List[Dict] = []
    for b in clean_blocks:
        for m in AMOUNT_RE.finditer(b):
            amt = to_float_amount(m)
            if amt is None:
                continue

            # waluta
            currency = (m.group('cur') or pick_currency(b)).upper().replace('ZŁ','PLN')

            # odrzucamy fałszywki typu "1.00 2.00 3.00" bez 'PLN', ale zostawiamy jeśli w linii jest PLN/zł
            if 'pln' not in b.lower() and 'zł' not in b.lower():
                # jeśli w nazwie pliku jest _wyciag_, to zwykle wartości w tabeli mają walutę w kolumnie
                pass

            # daty
            op_date, op_dt = parse_any_date(b)
            value_date = None
            # spróbuj z etykiet
            if not op_date:
                # czasem daty są w osobnych kolumnach — fallback z nazwy pliku: 'YYYY-MM - ...'
                prefix = path.name[:7]
                if re.match(r'^\d{4}-\d{2}$', prefix):
                    op_date = f"{prefix}-01"
            # Data waluty z całej strony — poszukaj w najbliższym bloku
            if 'data waluty' in b.lower():
                dv = find_label_value(b, LAB_VALUE_DATE)
                if dv:
                    donly, _ = parse_any_date(dv)
                    if donly:
                        value_date = donly
            # dodatkowo spróbuj przeglądu całego HTML (pojedyncze wystąpienia):
            if not value_date:
                body_txt = normalize_spaces(soup.get_text(" "))
                if 'data waluty' in body_txt.lower():
                    # prymitywne przybliżenie — pierwsza 'Data waluty: ...'
                    for seg in body_txt.split('Data waluty'):
                        dm = DATE_ISO_RE.search(seg) or DATE_DOT_RE.search(seg)
                        if dm:
                            if dm.re is DATE_ISO_RE:
                                y, mo, d = dm.groups()
                                value_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                            else:
                                d, mo, y = dm.groups()
                                value_date = f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
                            break

            # tytuł / opis
            title = find_label_value(b, LAB_TITLE) or b[:300]

            # kontra-partner: wybór labeli zależny od kierunku
            # najpierw zgadnij kierunek (tymczasowo — po kwocie/terminach)
            tmp_dir = guess_direction(amt, b)
            if tmp_dir == 'debet':
                cp = find_label_value(b, LAB_COUNTERPARTY_OUT) or find_label_value(b, LAB_COUNTERPARTY_IN)
            else:
                cp = find_label_value(b, LAB_COUNTERPARTY_IN) or find_label_value(b, LAB_COUNTERPARTY_OUT)

            # lokalizacja/adres/ref/telefon
            location = find_label_value(b, LAB_LOCATION)
            address  = find_label_value(b, LAB_ADDRESS)
            refno    = find_label_value(b, LAB_REFNO)
            phone    = find_label_value(b, LAB_PHONE)

            # doprecyzuj kierunek: minus = debet; plus = kredyt
            direction = 'debet' if amt < 0 else ('kredyt' if amt > 0 else tmp_dir)

            # normalizacje
            if direction == 'debet' and amt > 0:
                amt = -abs(amt)
            if direction == 'kredyt' and amt < 0:
                amt = abs(amt)

            # zbuduj rekord
            op_date_final = op_date or (value_date or None) or None
            if op_date_final:
                ym = month_from_date(op_date_final)
            else:
                # fallback z nazwy pliku
                prefix = path.name[:7]
                ym = prefix if re.match(r'^\d{4}-\d{2}$', prefix) else None

            row = {
                "ym": ym,
                "op_date": op_date_final,
                "op_datetime": op_dt,
                "value_date": value_date,
                "direction": direction,
                "amount": float(amt),
                "currency": currency,
                "title": title,
                "counterparty": cp,
                "location": location,
                "address": address,
                "reference_no": refno,
                "phone": phone,
                "source_file": str(path),
            }
            # odfiltruj ewidentne wiersze-salda
            if any(w in (title or '').lower() for w in BALANCE_WORDS):
                continue

            row["row_hash"] = compute_row_hash(path, row["op_date"] or (row["ym"] or "0000-00") + "-01", row["amount"], row["title"] or "")
            txs.append(row)

    return txs


# ------ Zapisy do bazy ------

def ensure_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(DDL)

def insert_transactions(rows: List[Dict]):
    with sqlite3.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR IGNORE INTO transactions
               (ym, op_date, op_datetime, value_date, direction, amount, currency, title,
                counterparty, location, address, reference_no, phone, source_file, row_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [(
                r["ym"], r["op_date"], r["op_datetime"], r["value_date"], r["direction"], r["amount"], r["currency"],
                r["title"], r["counterparty"], r["location"], r["address"], r["reference_no"], r["phone"],
                r["source_file"], r["row_hash"]
            ) for r in rows]
        )
        con.commit()


# ------ CLI ------

def collect_files(src: Path, month: Optional[str]) -> List[Path]:
    pats = ("*.html", "*.htm")
    files: List[Path] = []
    for p in pats:
        files.extend(src.glob(p))
    files.sort()
    if month:
        files = [f for f in files if f.name.startswith(month)]
    return files

def main():
    ap = argparse.ArgumentParser(description="Parser wyciągów HTML do SQLite (tabela transactions).")
    ap.add_argument("--src", default=str(Path("~/Inteligo").expanduser()), help="Folder z plikami HTML (domyślnie ~/Inteligo)")
    ap.add_argument("--month", default="", help='Opcjonalnie zawęź do prefiksu pliku "YYYY-MM" (np. 2025-08)')
    args = ap.parse_args()

    src = Path(args.src).expanduser()
    month = args.month.strip() or None

    ensure_db()

    all_rows: List[Dict] = []
    for path in collect_files(src, month):
        try:
            rows = extract_transactions_from_html(path)
            all_rows.extend(rows)
        except Exception as e:
            # Nie płaczemy nad jednym fikołkiem — lecimy dalej.
            continue

    insert_transactions(all_rows)

    print("@#@OK@#@")
    print(f"@#@Zapisano rekordów: {len(all_rows)}@#@")
    if month:
        print(f"@#@Zakres: {month}@#@")
    print("@#@Tabela: transactions, baza: {DB}@#@".replace("{DB}", str(DB_PATH)))

if __name__ == "__main__":
    main()
