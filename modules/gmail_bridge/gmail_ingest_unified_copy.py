import os, re, sys, sqlite3, datetime, hashlib

# ====== GMAIL BRIDGE (Twoje istniejące funkcje) ======
sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))
import gmail_bridge as gb  # korzysta z: load_service(), gmail_list_all_ids(), _msg_text(), _header()

DB = os.path.expanduser('~/.local/share/bankdb/bank.db')

# ====== utils ======
def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')

def norm_amt(s: str) -> float:
    return round(float(s.replace("\xa0","").replace(" ","").replace(",", ".")), 2)

def to_lines(text: str):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]

def normalize_counterparty(s: str) -> str:
    if not s: return ""
    s = s.replace("\xa0"," ").strip()
    s = re.sub(r'\s+', ' ', s)
    # skracamy krzyki-miasta na końcu, jeśli są same wielkie literki
    parts = s.split()
    if len(parts) >= 2 and parts[-1].isupper() and len(parts[-1]) >= 3:
        s = " ".join(parts[:-1])
    return s[:120]

# ====== SQL: tabela docelowa + migracje ======
def ensure_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # główna tabela (twarda, nie widok)
    cur.execute("""CREATE TABLE IF NOT EXISTS transactions_final(
      id INTEGER PRIMARY KEY,
      ym TEXT, op_date TEXT, value_date TEXT,
      direction TEXT, amount REAL, currency TEXT,
      title TEXT, counterparty TEXT, source_hint TEXT,
      tx_hash TEXT UNIQUE, created_at TEXT
    )""")
    # migracje: nowe kolumny
    def ensure_col(name, ddl):
        cur.execute("PRAGMA table_info(transactions_final)")
        cols = {r[1] for r in cur.fetchall()}
        if name not in cols:
            cur.execute(f"ALTER TABLE transactions_final ADD COLUMN {ddl}")

    ensure_col("biz_hash",   "biz_hash TEXT UNIQUE")
    ensure_col("is_pending", "is_pending INTEGER DEFAULT 0")
    ensure_col("category",   "category TEXT")
    ensure_col("first_source","first_source TEXT")
    ensure_col("sources_seen","sources_seen TEXT")
    ensure_col("updated_at", "updated_at TEXT")
    con.commit()
    # indeksy
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tfinal_bizhash ON transactions_final(biz_hash)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_tfinal_ym ON transactions_final(ym)")
    cur.execute("CREATE INDEX IF NOT EXISTS ix_tfinal_opdate ON transactions_final(op_date)")
    con.commit()
    return con

# ====== Reguły parsowania ======
RE_PLUS_AMT   = re.compile(r"\+\s*([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
RE_MINUS_AMT  = re.compile(r"-\s*([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
RE_ANY_AMT    = re.compile(r"([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
RE_KWOTA_OP   = re.compile(r"Kwota\s+operacji\s+([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)", re.I)
RE_DATA_WAL   = re.compile(r"Data\s+waluty[: ]\s*(\d{4}-\d{2}-\d{2})", re.I)
RE_NADAWCA    = re.compile(r"nadawca:\s*([^\n\r,]+)", re.I)
RE_ODBIORCA   = re.compile(r"odbiorca:\s*([^\n\r,]+)", re.I)
RE_SPRZEDAWCA = re.compile(r"sprzedawca:\s*([^\n\r,]+)", re.I)
RE_TYTUL      = re.compile(r"tytuł:\s*([^\n\r]+)", re.I)

FUEL_VENDORS = ["orlen","pkn orlen","circle k","bp","moya","lotos","avia","amic","shell","statoil","total"]
ATM_WORDS    = ["bankomat","wypłata z bankomatu","wplatomat","atm"]
PHONE_XFER   = ["przelew na telefon","blik na telefon","blik przelew na telefon","blik p2p"]

def pick_date(text: str, ts_ms: int) -> str:
    m = RE_DATA_WAL.search(text or "")
    if m: return m.group(1)
    return datetime.datetime.fromtimestamp(int(ts_ms)/1000).strftime("%Y-%m-%d")

def detect_block(text: str) -> str:
    low = (text or "").lower()
    if "autoryzacja transakcji kartowej" in low: return "card_auth"
    if "\nuznanie\n" in low or " uznanie" in low: return "income"
    if "\nobciążenie\n" in low or " obciążenie" in low: return "charge"
    return "unknown"

def categorize(direction: str, counterparty: str, title: str, text_all: str) -> str:
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

def parse_message(msg: dict):
    subj = gb._header(msg, "Subject") or ""
    body = gb._msg_text(msg)
    text = f"{subj}\n{body}"
    ts_ms = int(msg.get("internalDate","0"))
    op_date = pick_date(text, ts_ms)
    ym = op_date[:7]
    currency = "PLN"
    lines = to_lines(text)
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
            # vendor/city po linii z kwotą
            idx = next((i for i,ln in enumerate(lines) if RE_KWOTA_OP.search(ln) or RE_ANY_AMT.search(ln)), None)
            vend = city = ""
            if idx is not None:
                for j in range(idx+1, min(idx+4, len(lines))):
                    if lines[j].lower().startswith("dostępne"):
                        break
                    if not vend: vend = lines[j]; continue
                    if not city: city = lines[j]; break
            counterparty = normalize_counterparty(vend) or "(nieznany)"
            title = f"{vend} {city}".strip() or subj

    elif block == "income":
        section = text.split("Data waluty")[0]
        m_amt = RE_PLUS_AMT.search(section) or RE_ANY_AMT.search(section)
        if m_amt:
            amount = abs(norm_amt(m_amt.group(1)))
            direction = "in"
            source_hint = "mail:income"
            m_cp = RE_NADAWCA.search(text)
            counterparty = normalize_counterparty(m_cp.group(1)) if m_cp else ""
            if not counterparty:
                idx = next((i for i,ln in enumerate(lines) if "uznanie" in ln.lower()), None)
                if idx is not None and idx+1 < len(lines): counterparty = normalize_counterparty(lines[idx+1])

    elif block == "charge":
        m_amt = RE_MINUS_AMT.search(text) or RE_ANY_AMT.search(text)
        if m_amt:
            amount = -abs(norm_amt(m_amt.group(1)))
            direction = "out"
            source_hint = "mail:charge"
            m_sp = RE_SPRZEDAWCA.search(text)
            m_od = RE_ODBIORCA.search(text)
            counterparty = normalize_counterparty(m_sp.group(1) if m_sp else (m_od.group(1) if m_od else ""))
            m_ty = RE_TYTUL.search(text)
            if m_ty:
                title = m_ty.group(1).strip()
            else:
                idx = next((i for i,ln in enumerate(lines) if RE_MINUS_AMT.search(ln) or RE_ANY_AMT.search(ln)), None)
                vend = city = ""
                if idx is not None:
                    for j in range(idx+1, min(idx+4, len(lines))):
                        if lines[j].lower().startswith("dostępne"): break
                        if not vend: vend = lines[j]; continue
                        if not city: city = lines[j]; break
                if not counterparty: counterparty = normalize_counterparty(vend) or "(nieznany)"
                if title == subj and vend: title = f"{vend} {city}".strip()

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

def biz_hash_for(row: dict) -> str:
    key = f"{row['op_date']}|{round(abs(row['amount']),2)}|{normalize_counterparty(row['counterparty'])}|{row['currency']}|{row['direction']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()

def tx_hash_for(row: dict) -> str:
    key = f"{row['op_date']}|{row['amount']}|{row['counterparty']}|{row['currency']}|{row['direction']}|{row['source_hint']}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()

def upsert_row(cur, row: dict):
    created_at = now_iso()
    updated_at = created_at
    biz_hash = biz_hash_for(row)
    tx_hash  = tx_hash_for(row)
    # spróbuj insert po biz_hash (unikalny)
    try:
        cur.execute("""INSERT INTO transactions_final
          (ym, op_date, value_date, direction, amount, currency, title, counterparty, source_hint,
           tx_hash, created_at, biz_hash, is_pending, category, first_source, sources_seen, updated_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
          (row["ym"], row["op_date"], row["value_date"], row["direction"], row["amount"], row["currency"],
           row["title"], row["counterparty"], row["source_hint"], tx_hash, created_at, biz_hash,
           row["is_pending"], row["category"], row["source_hint"], row["source_hint"], updated_at)
        )
        return 1  # inserted
    except sqlite3.IntegrityError:
        # istnieje – aktualizujemy źródła i pending
        cur.execute("""SELECT is_pending, sources_seen, first_source FROM transactions_final WHERE biz_hash=?""", (biz_hash,))
        r = cur.fetchone()
        if not r:
            return 0
        was_pending, sources_seen, first_source = r
        sources = set((sources_seen or "").split(",")) if sources_seen else set()
        sources.add(row["source_hint"])
        # jeśli przyszło twarde księgowanie (charge/income) – zdejmij pending
        new_pending = 0 if row["source_hint"] in ("mail:charge","mail:income") else was_pending
        cur.execute("""UPDATE transactions_final
                       SET sources_seen=?, is_pending=?, updated_at=?
                       WHERE biz_hash=?""",
                    (",".join(sorted(s for s in sources if s)), new_pending, now_iso(), biz_hash))
        return 0  # updated

def main():
    # Argument opcjonalny: query Gmail, np. "newer_than:3d"
    user_q = " ".join(sys.argv[1:]).strip() or "newer_than:3d"
    q = f"from:inteligo@inteligo.pl {user_q}"

    con = ensure_db()
    cur = con.cursor()
    svc = gb.load_service()

    ids = gb.gmail_list_all_ids(svc, q, max_per_page=500)
    inserted = updated_or_skipped = 0

    for mid in ids:
        msg = svc.users().messages().get(userId="me", id=mid, format="full").execute()
        parsed = parse_message(msg)
        if not parsed:
            updated_or_skipped += 1
            continue
        inserted += upsert_row(cur, parsed)  # 1 = inserted, 0 = updated/ignored

    con.commit()
    con.close()
    print(f"@#@Ingest OK. Dodane: {inserted}, reszta (update/skip): {updated_or_skipped}@#@")

if __name__ == "__main__":
    main()
