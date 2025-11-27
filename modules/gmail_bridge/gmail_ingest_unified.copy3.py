#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, sqlite3, datetime, hashlib

# ====== GMAIL BRIDGE ======
sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))
import gmail_bridge as gb  # load_service(), gmail_list_all_ids(), _msg_text(), _header()

DB = os.path.expanduser('~/.local/share/bankdb/bank.db')

# ====== utils ======
def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')

def norm_amt(s: str) -> float:
    return round(float(s.replace("\xa0", "").replace(" ", "").replace(",", ".")), 2)

def to_lines(text: str):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

def normalize_counterparty(s: str) -> str:
    if not s:
        return ""
    s = s.replace("\xa0", " ").strip()
    s = re.sub(r'\s+', ' ', s)
    parts = s.split()
    if len(parts) >= 2 and parts[-1].isupper() and len(parts[-1]) >= 3:
        s = " ".join(parts[:-1])
    return s[:120]

# ====== SQL: tabela docelowa + migracje ======
def ensure_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions_final(
            id INTEGER PRIMARY KEY,
            ym TEXT,
            op_date TEXT,
            value_date TEXT,
            direction TEXT,
            amount REAL,
            currency TEXT,
            title TEXT,
            counterparty TEXT,
            source_hint TEXT,
            tx_hash TEXT,
            biz_hash TEXT,
            is_pending INTEGER DEFAULT 0,
            category TEXT,
            first_source TEXT,
            sources_seen TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cols = {r[1] for r in cur.execute("PRAGMA table_info(transactions_final)").fetchall()}
    def add_col(name, ddl):
        if name not in cols:
            cur.execute(f"ALTER TABLE transactions_final ADD COLUMN {ddl}")
    add_col("tx_hash", "tx_hash TEXT")
    add_col("biz_hash", "biz_hash TEXT")
    add_col("is_pending", "is_pending INTEGER DEFAULT 0")
    add_col("category", "category TEXT")
    add_col("first_source", "first_source TEXT")
    add_col("sources_seen", "sources_seen TEXT")
    add_col("created_at", "created_at TEXT")
    add_col("updated_at", "updated_at TEXT")
    add_col("source_hint", "source_hint TEXT")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tfinal_ym ON transactions_final(ym)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_tfinal_opdate ON transactions_final(op_date)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tfinal_txhash ON transactions_final(tx_hash)")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tfinal_bizhash ON transactions_final(biz_hash) WHERE biz_hash IS NOT NULL")
    con.commit()
    return con

# ====== Reguły parsowania ======
RE_PLUS_AMT   = re.compile(r"\+\s*([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
RE_MINUS_AMT  = re.compile(r"-\s*([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
RE_ANY_AMT    = re.compile(r"([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
RE_KWOTA_OP   = re.compile(r"Kwota\s+operacji\s+([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)", re.I)
RE_DATA_WAL   = re.compile(r"Data\s+waluty[: ]\s*(\d{4}-\d{2}-\d{2})", re.I)
RE_NADAWCA    = re.compile(r"nadawca[:\s]*([A-Za-z0-9\.\-\sąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)", re.I)
RE_ODBIORCA   = re.compile(r"odbiorca[:\s]*([A-Za-z0-9\.\-\sąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)", re.I)
RE_SPRZEDAWCA = re.compile(r"sprzedawca[:\s]*([A-Za-z0-9\.\-_/:\sąćęłńóśźżĄĆĘŁŃÓŚŹŻ]+)", re.I)
RE_TYTUL      = re.compile(r"tytuł[:\s]*([^\n\r]+)", re.I)

FUEL_VENDORS = ["orlen","pkn orlen","circle k","bp","moya","lotos","avia","amic","shell","statoil","total","stacja paliw"]
ATM_WORDS = ["bankomat","wypłata z bankomatu","wpłatomat","atm"]
PHONE_XFER = ["przelew na telefon","blik na telefon","blik przelew na telefon","blik p2p"]

def pick_date(text: str, ts_ms: int) -> str:
    m = RE_DATA_WAL.search(text or "")
    if m:
        return m.group(1)
    return datetime.datetime.fromtimestamp(int(ts_ms)/1000).strftime("%Y-%m-%d")

def detect_block(text: str) -> str:
    low = (text or "").lower()
    if "autoryzacja transakcji kartowej" in low:
        return "card_auth"
    if "uznanie" in low:
        return "income"
    if "obciążenie" in low:
        return "charge"
    if "przelew na telefon" in low or "blik na telefon" in low or "blik p2p" in low:
        return "phone"
    return "unknown"

def categorize(direction, counterparty, title, text_all):
    t = f"{counterparty} {title} {text_all}".lower()
    if direction == "in":
        return "income"
    if any(w in t for w in ATM_WORDS):
        return "atm"
    if any(w in t for w in PHONE_XFER):
        return "phone_transfer"
    if any(v in t for v in FUEL_VENDORS):
        return "fuel"
    return "card" if direction == "out" else "other"

# ====== Główna funkcja parsowania ======
def parse_message(msg: dict):
    subj = gb._header(msg, "Subject") or ""
    body = gb._msg_text(msg)
    text = f"{subj}\n{body}"
    ts_ms = int(msg.get("internalDate","0"))
    op_date = pick_date(text, ts_ms)
    ym = op_date[:7]
    currency = "PLN"
    block = detect_block(text)
    amount = None
    direction = None
    counterparty = ""
    title = subj
    source_hint = "mail:unknown"
    is_pending = 0

    if block == "card_auth":
        m_amt = RE_KWOTA_OP.search(text) or RE_ANY_AMT.search(text)
        if m_amt:
            amount = -abs(norm_amt(m_amt.group(1)))
            direction = "out"
            source_hint = "mail:card_auth"
            is_pending = 1

    elif block == "income":
        m_amt = RE_PLUS_AMT.search(text)
        if m_amt:
            amount = abs(norm_amt(m_amt.group(1)))
            direction = "in"
            source_hint = "mail:income"

    elif block == "charge":
        m_amt = RE_MINUS_AMT.search(text)
        if m_amt:
            amount = -abs(norm_amt(m_amt.group(1)))
            direction = "out"
            source_hint = "mail:charge"
        m_sp = RE_SPRZEDAWCA.search(text)
        if m_sp:
            counterparty = normalize_counterparty(m_sp.group(1))

    if amount is None or direction is None:
        return None

    cat = categorize(direction, counterparty, title, text)
    return {
        "ym": ym,
        "op_date": op_date,
        "value_date": op_date,
        "direction": direction,
        "amount": round(amount, 2),
        "currency": currency,
        "title": title or ("Uznanie" if direction=="in" else "Transakcja"),
        "counterparty": counterparty or "(nieznany)",
        "source_hint": source_hint,
        "is_pending": is_pending,
        "category": cat,
    }
# ====== INSERT / UPDATE ======

def biz_hash_for(row):
    # hash oparty tylko na danych kluczowych transakcji (data, kwota, waluta, kierunek)
    key = f"{row['op_date']}|{round(abs(row['amount']),2)}|{row['currency']}|{row['direction']}"
    return hashlib.sha1(key.encode('utf-8')).hexdigest()

def tx_hash_for(row):
    # hash unikalny dla źródła i kierunku (ignoruje kontrahenta/tytuł)
    key = f"{row['op_date']}|{row['amount']}|{row['currency']}|{row['direction']}|{row['source_hint']}"
    return hashlib.sha1(key.encode('utf-8')).hexdigest()


def upsert_row(cur, row: dict):
    created_at = now_iso()
    updated_at = created_at
    biz_hash_new = biz_hash_for(row)
    tx_hash_new = tx_hash_for(row)

    # próbuj zmergować wcześniejszą autoryzację do obciążenia
    if row["source_hint"] in ("mail:charge", "mail:income"):
        cur.execute("""
            SELECT id, sources_seen, first_source, counterparty, title
            FROM transactions_final
            WHERE is_pending=1
              AND op_date = ?
              AND ABS(amount - ?) < 0.01
              AND direction = ?
            ORDER BY id ASC
            LIMIT 1
        """, (row["op_date"], row["amount"], row["direction"]))
        pend = cur.fetchone()
        if pend:
            pend_id, sources_seen, first_source, pend_cp, pend_title = pend
            srcs = set((sources_seen or "").split(",")) if sources_seen else set()
            srcs.add(row["source_hint"])
            new_cp = row["counterparty"] or pend_cp or "(nieznany)"
            new_title = row["title"] or pend_title or ("Uznanie" if row["direction"]=="in" else "Transakcja")
            new_cat = row.get("category")
            cur.execute("""
                UPDATE transactions_final
                SET counterparty=?, title=?, source_hint=?, sources_seen=?, is_pending=0,
                    category=?, updated_at=?, biz_hash=?, tx_hash=?
                WHERE id=?
            """, (new_cp, new_title, row["source_hint"], ",".join(sorted(srcs)), new_cat,
                  now_iso(), biz_hash_new, tx_hash_new, pend_id))
            return 0

    try:
        cur.execute("""
            INSERT INTO transactions_final
            (ym, op_date, value_date, direction, amount, currency, title, counterparty,
             source_hint, tx_hash, created_at, biz_hash, is_pending, category,
             first_source, sources_seen, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (row["ym"], row["op_date"], row["value_date"], row["direction"],
              row["amount"], row["currency"], row["title"], row["counterparty"],
              row["source_hint"], tx_hash_new, created_at, biz_hash_new,
              row["is_pending"], row["category"], row["source_hint"],
              row["source_hint"], updated_at))
        return 1

    except sqlite3.IntegrityError:
        cur.execute("""
            SELECT id, is_pending, sources_seen, first_source, counterparty, title
            FROM transactions_final
            WHERE biz_hash=?
        """, (biz_hash_new,))
        r = cur.fetchone()
        if not r:
            return 0
        row_id, was_pending, sources_seen, first_source, old_cp, old_title = r
        srcs = set((sources_seen or "").split(",")) if sources_seen else set()
        srcs.add(row["source_hint"])
        new_pending = 0 if row["source_hint"] in ("mail:charge", "mail:income") else was_pending
        new_cp = row["counterparty"] or old_cp
        new_title = row["title"] or old_title

        cur.execute("""
            UPDATE transactions_final
            SET counterparty=?, title=?, sources_seen=?, is_pending=?, updated_at=?
            WHERE id=?
        """, (new_cp, new_title, ",".join(sorted(srcs)), new_pending, now_iso(), row_id))
        return 0

# ====== MAIN ======
def main():
    user_q = " ".join(sys.argv[1:])
    q = user_q or "newer_than:3d"
    con = ensure_db()
    cur = con.cursor()
    svc = gb.load_service()
    ids = gb.gmail_list_all_ids(svc, q, max_per_page=500)
    inserted = updated_or_skipped = 0
    for mid in ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        row = parse_message(msg)
        if not row:
            continue
        res = upsert_row(cur, row)
        if res:
            inserted += 1
        else:
            updated_or_skipped += 1
    con.commit()
    print(f"@#@Ingest OK. Dodane: {inserted}, reszta (update/skip): {updated_or_skipped}@#@")

    # --- [LOG AKTUALIZACJI INGEST] ---
    try:
        from datetime import datetime
        log_path = os.path.expanduser("~/.local/share/bankdb/ingest_log.txt")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} ingest OK\n")
    except Exception as e:
        print(f"⚠️ Nie udało się zapisać do ingest_log.txt: {e}")

if __name__ == "__main__":
    main()
