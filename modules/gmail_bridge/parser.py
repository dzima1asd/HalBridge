#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
html_to_transactions_canon.py
Parser wyciągów HTML -> tabela SQLite `transactions_canon` (z deduplikacją między plikami).

Zasady:
- rozpoznaje kolumny po nagłówkach (pl, bez polskich znaków też),
- bierze jedną kwotę z wiersza (Obciążenia -> debet, Uznania -> kredyt; inaczej Kwota z +/-),
- pomija wiersze typu suma/razem/podsumowanie/saldo,
- tx_hash nie zawiera nazwy pliku, więc ta sama operacja z kopii "(1).html" nie dubluje się.
"""

from __future__ import annotations
import argparse, re, sqlite3, hashlib
from pathlib import Path
from typing import List, Dict, Optional
from bs4 import BeautifulSoup

DB_PATH = Path("~/.local/share/bankdb/bank.db").expanduser()

DDL = """
CREATE TABLE IF NOT EXISTS transactions_canon(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ym TEXT,
  op_date TEXT,
  value_date TEXT,
  direction TEXT CHECK(direction IN ('debet','kredyt')),
  amount REAL,
  currency TEXT,
  title TEXT,
  counterparty TEXT,
  source_hint TEXT,   -- np. nazwa pliku (info, nie w hashu)
  tx_hash TEXT UNIQUE,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_txc_ym ON transactions_canon(ym);
CREATE INDEX IF NOT EXISTS idx_txc_opdate ON transactions_canon(op_date);
"""

AMOUNT_RE = re.compile(r'([+-−]?\s*\d[\d\s\u00A0]{0,12}(?:[.,]\d{2})?)\s*(PLN|zł)?\b', re.I)
DATE_ISO_RE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
DATE_DOT_RE = re.compile(r'\b(\d{2})[.\-\/](\d{2})[.\-\/](\d{4})\b')

NEG_KEYS = ('obciąż', 'obciaz', 'obciąz')
POS_KEYS = ('uznani', 'uznanie')
AMT_KEYS = ('kwota',)
CUR_KEYS = ('waluta',)
TITLE_KEYS = ('tytuł','tytul','opis','szczegóły','szczegoly','nazwa operacji')
CP_OUT_KEYS = ('odbiorca','adresat','sprzedawca','merchant')
CP_IN_KEYS  = ('nadawca','zleceniodawca')
DATE_KEYS = ('data', 'data operacji', 'data transakcji')
VAL_DATE_KEYS = ('data waluty',)

SKIP_WORDS = ('suma','razem','podsumowanie','saldo','dostępne','dostepne')

def norm(s: str) -> str:
    return " ".join((s or "").replace("\u00A0"," ").split())

def to_amount(txt: str) -> Optional[float]:
    m = AMOUNT_RE.search(txt)
    if not m: return None
    s = m.group(1)
    s = s.replace(" ", "").replace("\u00A0","").replace(",", ".").replace("−","-")
    try:
        return float(s)
    except Exception:
        return None

def parse_date(txt: str) -> Optional[str]:
    m = DATE_ISO_RE.search(txt)
    if m:
        y,mo,d = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    m = DATE_DOT_RE.search(txt)
    if m:
        d,mo,y = map(int, m.groups())
        return f"{y:04d}-{mo:02d}-{d:02d}"
    return None

def month_of(date: Optional[str]) -> Optional[str]:
    return date[:7] if date else None

def find_idx(headers: List[str], keys: tuple) -> Optional[int]:
    for i,h in enumerate(headers):
        hl = h.lower()
        if any(k in hl for k in keys):
            return i
    return None

def cell(cells: List[str], idx: Optional[int]) -> str:
    return cells[idx] if idx is not None and idx < len(cells) else ""

def txhash(op_date: str, value_date: str, amount: float, currency: str, title: str, cp: str) -> str:
    base = f"{op_date}|{value_date}|{amount:.2f}|{currency.upper()}|{title.strip().lower()[:80]}|{cp.strip().lower()[:80]}"
    return hashlib.sha256(base.encode("utf-8","ignore")).hexdigest()

def parse_table(table, source_hint: str) -> List[Dict]:
    # nagłówki
    hdr_tr = None
    for tr in table.find_all('tr'):
        ths = [norm(th.get_text(" ")) for th in tr.find_all('th')]
        if any(ths):
            hdr_tr = tr
            break
    if not hdr_tr:
        return []

    headers = [norm(th.get_text(" ")) for th in hdr_tr.find_all('th')]
    headers_l = [h.lower() for h in headers]

    # kolumny
    i_neg = find_idx(headers, NEG_KEYS)
    i_pos = find_idx(headers, POS_KEYS)
    i_amt = find_idx(headers, AMT_KEYS)
    i_cur = find_idx(headers, CUR_KEYS)
    i_title = find_idx(headers, TITLE_KEYS)
    i_cp_out = find_idx(headers, CP_OUT_KEYS)
    i_cp_in  = find_idx(headers, CP_IN_KEYS)
    i_date = find_idx(headers, DATE_KEYS)
    i_valdate = find_idx(headers, VAL_DATE_KEYS)

    if i_neg is None and i_pos is None and i_amt is None:
        # nie wygląda jak tabela z transakcjami
        return []

    rows: List[Dict] = []
    for tr in hdr_tr.find_all_next('tr'):
        if tr is hdr_tr: 
            continue
        tds = tr.find_all('td')
        if not tds:
            continue
        cells = [norm(td.get_text(" ")) for td in tds]
        whole = " | ".join(cells).lower()
        if any(w in whole for w in SKIP_WORDS):
            continue

        amt = None
        direction = None

        # priorytet: Obciążenia / Uznania
        if i_neg is not None:
            v = cell(cells, i_neg)
            if v:
                a = to_amount(v)
                if a is not None and abs(a) > 0:
                    amt = -abs(a)
                    direction = 'debet'
        if amt is None and i_pos is not None:
            v = cell(cells, i_pos)
            if v:
                a = to_amount(v)
                if a is not None and abs(a) > 0:
                    amt = abs(a)
                    direction = 'kredyt'
        if amt is None and i_amt is not None:
            v = cell(cells, i_amt)
            a = to_amount(v)
            if a is not None and abs(a) > 0:
                amt = a
                direction = 'debet' if a < 0 else 'kredyt'

        if amt is None:
            continue

        cur = (cell(cells, i_cur) or "PLN").upper().replace("ZŁ","PLN")
        title = cell(cells, i_title) or cells[-1]  # często opis na końcu
        cp = cell(cells, i_cp_out) or cell(cells, i_cp_in) or ""

        op_date = parse_date(cell(cells, i_date)) or parse_date(" ".join(cells))  # fallback
        value_date = parse_date(cell(cells, i_valdate)) or None
        ym = month_of(op_date) or month_of(value_date)

        th = txhash(op_date or "", value_date or "", float(amt), cur, title, cp)

        rows.append({
            "ym": ym,
            "op_date": op_date,
            "value_date": value_date,
            "direction": direction,
            "amount": float(amt),
            "currency": cur,
            "title": title,
            "counterparty": cp,
            "source_hint": source_hint,
            "tx_hash": th,
        })
    return rows

def parse_file(path: Path) -> List[Dict]:
    html = path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    out: List[Dict] = []
    for table in soup.find_all("table"):
        out.extend(parse_table(table, source_hint=path.name))
    return out

def ensure_db():
    with sqlite3.connect(DB_PATH) as con:
        con.executescript(DDL)

def insert_rows(rows: List[Dict]):
    if not rows: 
        return
    with sqlite3.connect(DB_PATH) as con:
        con.executemany(
            """INSERT OR IGNORE INTO transactions_canon
               (ym, op_date, value_date, direction, amount, currency, title, counterparty, source_hint, tx_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [(
                r["ym"], r["op_date"], r["value_date"], r["direction"], r["amount"], r["currency"],
                r["title"], r["counterparty"], r["source_hint"], r["tx_hash"]
            ) for r in rows]
        )
        con.commit()

def collect_files(src: Path) -> List[Path]:
    files: List[Path] = []
    for pat in ("*.html","*.htm"):
        files.extend(src.glob(pat))
    files.sort()
    return files

def main():
    ap = argparse.ArgumentParser(description="Parser HTML -> transactions_canon")
    ap.add_argument("--src", default=str(Path("~/Inteligo").expanduser()))
    args = ap.parse_args()

    ensure_db()
    src = Path(args.src).expanduser()
    total = 0
    for p in collect_files(src):
        try:
            rows = parse_file(p)
            insert_rows(rows)
            total += len(rows)
        except Exception:
            continue
    print("@#@OK_CANON@#@")
    print(f"@#@Zapisano rekordów (po dedupe na hash): {total}@#@")

if __name__ == "__main__":
    main()
