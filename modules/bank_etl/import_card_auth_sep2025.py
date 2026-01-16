import os, re, sqlite3, datetime, hashlib, sys
# dostęp do gmail_bridge
sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))
import gmail_bridge as gb

DB = os.path.expanduser('~/.local/share/bankdb/bank.db')
os.makedirs(os.path.dirname(DB), exist_ok=True)
con = sqlite3.connect(DB)
cur = con.cursor()

# Używamy TYLKO tabeli docelowej, bo "transactions" jest widokiem.
cur.execute("""CREATE TABLE IF NOT EXISTS transactions_final(
  id INTEGER PRIMARY KEY,
  ym TEXT, op_date TEXT, value_date TEXT,
  direction TEXT, amount REAL, currency TEXT,
  title TEXT, counterparty TEXT, source_hint TEXT,
  tx_hash TEXT, created_at TEXT
)""")
cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_tfinal_txhash ON transactions_final(tx_hash)")
con.commit()

svc = gb.load_service()
# wrzesień 2025
q = "from:inteligo@inteligo.pl after:2025/09/01 before:2025/10/01"
ids = gb.gmail_list_all_ids(svc, q, max_per_page=500)

amt_re  = re.compile(r"Kwota\s+operacji\s+([\d\s\u00A0]+(?:[.,]\d{2})?)\s*(?:PLN|zł)", re.I)
card4_re= re.compile(r"Karta\s+(\d{4})", re.I)
date_re = re.compile(r"\b(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\b")
is_auth = re.compile(r"Autoryzacja\s+transakcji\s+kartowej", re.I)

def norm_amt(s:str)->float:
    s = s.replace("\xa0","").replace(" ","").replace(",",".")
    return round(float(s),2)

inserted = skipped = 0

for mid in ids:
    msg  = svc.users().messages().get(userId='me', id=mid, format='full').execute()
    body = gb._msg_text(msg)
    subj = ""
    for h in msg.get("payload",{}).get("headers",[]):
        if h.get("name","").lower()=="subject":
            subj = h.get("value","")
            break
    text = subj + "\n" + body

    # tylko autoryzacje kartowe
    if not is_auth.search(text):
        continue

    m_amt = amt_re.search(text)
    if not m_amt:
        skipped += 1
        continue
    amount = -abs(norm_amt(m_amt.group(1)))   # wydatek => ujemny

    # vendor i miasto to zwykle 1-2 linie po kwocie
    lines = [ln.strip() for ln in text.splitlines()]
    vendor = city = ""
    idx = next((i for i,ln in enumerate(lines) if amt_re.search(ln)), None)
    if idx is not None:
        for j in range(idx+1, min(idx+4, len(lines))):
            if lines[j] and not lines[j].lower().startswith("dostępne"):
                if not vendor: vendor = lines[j]
                elif not city: city = lines[j]; break

    m_card = card4_re.search(text)
    last4 = m_card.group(1) if m_card else "????"

    m_dt = date_re.search(text)
    if m_dt:
        op_date = m_dt.group(1)
    else:
        ts_ms = int(msg.get("internalDate","0"))
        op_date = datetime.datetime.fromtimestamp(ts_ms/1000).strftime("%Y-%m-%d")

    ym = op_date[:7]
    currency = "PLN"
    title = f"{vendor} {city}".strip()
    counterparty = vendor or "(nieznany)"
    direction = "out"
    source_hint = "mail:card_auth"
    key = f"{op_date}|{amount}|{counterparty}|{last4}|{currency}"
    tx_hash = hashlib.sha1(key.encode("utf-8")).hexdigest()
    created_at = datetime.datetime.now().isoformat(timespec='seconds')

    row = (ym, op_date, op_date, direction, amount, currency, title, counterparty, source_hint, tx_hash, created_at)

    # upsert bez dubli – tylko do tabeli docelowej
    cur.execute("""INSERT OR IGNORE INTO transactions_final
        (ym, op_date, value_date, direction, amount, currency, title, counterparty, source_hint, tx_hash, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""", row)
    inserted += 1

con.commit()
con.close()
print(f"@#@Załadowano autoryzacje kartowe wrzesień 2025: {inserted}, pominięte (brak kwoty): {skipped}@#@")
