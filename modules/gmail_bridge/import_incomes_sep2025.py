import os, re, sqlite3, datetime, hashlib, sys
# dostęp do gmail_bridge
sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))
import gmail_bridge as gb

DB = os.path.expanduser('~/.local/share/bankdb/bank.db')
con = sqlite3.connect(DB)
cur = con.cursor()

# Upewnij się, że tabele istnieją (unikamy widoków)
cur.execute("""CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  ym TEXT, op_date TEXT, value_date TEXT,
  direction TEXT, amount REAL, currency TEXT,
  title TEXT, counterparty TEXT, source_hint TEXT,
  tx_hash TEXT UNIQUE, created_at TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS transactions_final(
  id INTEGER PRIMARY KEY,
  ym TEXT, op_date TEXT, value_date TEXT,
  direction TEXT, amount REAL, currency TEXT,
  title TEXT, counterparty TEXT, source_hint TEXT,
  tx_hash TEXT UNIQUE, created_at TEXT
)""")
con.commit()

svc = gb.load_service()

# wrzesień 2025 (zmień zakres, jeśli chcesz)
q = "from:inteligo@inteligo.pl after:2025/09/01 before:2025/10/01 subject:\"Wiadomość z Inteligo\""
ids = gb.gmail_list_all_ids(svc, q, max_per_page=500)

AMT_PLUS_RE = re.compile(r"\+\s*([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)?", re.I)
AMT_ANY_RE  = re.compile(r"([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)\b", re.I)
DATA_WALUTY_RE = re.compile(r"Data\s+waluty\s+(\d{4}-\d{2}-\d{2})", re.I)
NADAWCA_RE  = re.compile(r"nadawca:\s*([^\n\r,]+)", re.I)

def norm_amt(s:str)->float:
    return float(s.replace("\xa0","").replace(" ","").replace(",","."))
def first(lines, pred):
    for ln in lines:
        if pred(ln): return ln
    return ""

inserted = skipped = 0

for mid in ids:
    msg  = svc.users().messages().get(userId='me', id=mid, format='full').execute()
    subj = gb._header(msg, "Subject") or ""
    body = gb._msg_text(msg)
    text = subj + "\n" + body

    # filtr: to mają być UZNANIA / PRZELEW PRZYCH / przych.
    low = text.lower()
    if not ("uznanie" in low or "przelew przych" in low or "przychodząc" in low):
        skipped += 1
        continue

    # kwota: preferuj linie z plusem przed "Data waluty"
    section = text.split("Data waluty")[0]
    m = AMT_PLUS_RE.search(section) or AMT_ANY_RE.search(section)
    if not m:
        skipped += 1
        continue
    amount = round(abs(norm_amt(m.group(1))), 2)  # przychód → dodatni

    # data operacji
    mdt = DATA_WALUTY_RE.search(text)
    if mdt:
        op_date = mdt.group(1)
    else:
        ts_ms = int(msg.get("internalDate","0"))
        op_date = datetime.datetime.fromtimestamp(ts_ms/1000).strftime("%Y-%m-%d")

    ym = op_date[:7]
    currency = "PLN"

    # kontrahent (nadawca) + tytuł
    mcp = NADAWCA_RE.search(text)
    counterparty = mcp.group(1).strip() if mcp else ""
    if not counterparty:
        # fallback: spróbuj wziąć linię po frazie "WPŁYW" lub "PRZELEW PRZYCH."
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        idx = None
        for i,ln in enumerate(lines):
            if "przelew przych" in ln.lower() or "uznanie" in ln.lower():
                idx = i; break
        if idx is not None and idx+1 < len(lines):
            counterparty = lines[idx+1][:120]
    title = subj if subj else "Uznanie"

    direction = "in"
    source_hint = "mail:income"
    key = f"{op_date}|{amount}|{counterparty}|{currency}|income"
    tx_hash = hashlib.sha1(key.encode("utf-8")).hexdigest()
    created_at = datetime.datetime.now().isoformat(timespec='seconds')

    row = (ym, op_date, op_date, direction, amount, currency, title, counterparty, source_hint, tx_hash, created_at)

    cur.execute("""INSERT OR IGNORE INTO transactions
      (ym, op_date, value_date, direction, amount, currency, title, counterparty, source_hint, tx_hash, created_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)""", row)
    cur.execute("""INSERT OR IGNORE INTO transactions_final
      (ym, op_date, value_date, direction, amount, currency, title, counterparty, source_hint, tx_hash, created_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)""", row)
    inserted += 1

con.commit()
con.close()
print(f"@#@Załadowano uznania wrzesień 2025: {inserted}, pominięte: {skipped}@#@")
