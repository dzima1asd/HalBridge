import os
import sys
import re
import sqlite3
import datetime
import base64
import csv
import codecs
import tempfile
import zipfile
sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))
import gmail_bridge as gb

sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))

from email.header import decode_header


def extract_op_date(text: str):
    """
    Z treści maila wyciąga datę operacji:
    - preferuje "Data operacji", potem "Data waluty"
    - obsługuje YYYY-MM-DD oraz DD.MM.YYYY
    Zwraca "YYYY-MM-DD" albo None.
    """
    if not text:
        return None
    t = text.replace('\xa0',' ')
    patterns = [
        r'(?i)Data\s+operacji[:\s]+(\d{4}-\d{2}-\d{2})',
        r'(?i)Data\s+operacji[:\s]+(\d{2}\.\d{2}\.\d{4})',
        r'(?i)Data\s+waluty[:\s]+(\d{4}-\d{2}-\d{2})',
        r'(?i)Data\s+waluty[:\s]+(\d{2}\.\d{2}\.\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            val = m.group(1)
            if '.' in val:
                d,mn,y = val.split('.')
                return f"{y}-{mn}-{d}"
            return val
    return None
sys.path.insert(0, os.path.expanduser('~/HALbridge/modules/gmail_bridge'))

def pick_amount(text, amts):
    # Wybiera sensowną kwotę z treści:
    # - pomija linie z 'Dostępne' lub 'Saldo'
    # - preferuje kwotę ze znakiem '+'
    # - fallback: pierwsza kwota z listy amts
    try:
        rx = gb.AMOUNT_RE
    except Exception:
        rx = None

    if rx:
        for m in rx.finditer(text):
            s, e = m.start(), m.end()
            ls = text.rfind("\n", 0, s) + 1
            le = text.find("\n", e)
            if le == -1:
                le = len(text)
            line = text[ls:le].lower()
            if ("dostępne" in line) or ("saldo" in line):
                continue
            if "+" in text[ls:s]:
                val = m.group(1).replace(" ", "").replace("\\xa0", "").replace(",", ".")
                try:
                    return round(float(val), 2)
                except:
                    pass
    # fallback
    if amts:
        v = str(amts[0]).replace(" ", "").replace("\\xa0", "").replace(",", ".")
        try:
            return round(float(v), 2)
        except:
            return amts[0]
    return 0.0

DB = os.path.expanduser('~/.local/share/bankdb/bank.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS tx (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  msg_id TEXT UNIQUE,
  ts INTEGER,
  ymd TEXT,
  sender TEXT,
  subject TEXT,
  category TEXT,
  amount REAL,
  amount_raw REAL,
  snippet TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_ymd ON tx(ymd);
CREATE INDEX IF NOT EXISTS idx_tx_cat ON tx(category);
"""

def ensure_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    con.commit()
    return con

def insert_tx(con, rec):
    con.execute("""INSERT OR IGNORE INTO tx
      (msg_id, ts, ymd, sender, subject, category, amount, amount_raw, snippet)
      VALUES (?,?,?,?,?,?,?,?,?)""",
      (rec['msg_id'], rec['ts'], rec['ymd'], rec['sender'], rec['subject'],
       rec['category'], rec['amount'], rec['amount_raw'], rec['snippet']))
    
def ingest(query):
    con = ensure_db()
    svc = gb.load_service()
    pageToken = None
    cnt=0
    while True:
        res = svc.users().messages().list(userId='me', q=query, pageToken=pageToken, maxResults=200).execute()
        for it in res.get('messages', []):
            msg = svc.users().messages().get(userId='me', id=it['id'], format='full').execute()
            subj = _h(msg,'Subject')
            body = gb._msg_text(msg)
            ymd = extract_op_date(body) or ymd
            # domyślna data z Gmaila
            ts_ms = int(msg.get('internalDate','0'))
            ymd = datetime.datetime.fromtimestamp(ts_ms/1000).strftime('%Y-%m-%d')
            # nadpisz, jeśli w treści jest Data operacji / Data waluty
            ymd = extract_op_date(body) or ymd
            cat = gb.classify_entry(subj, body)
            amts = gb._amounts(body + "\n" + subj)
            if not amts:
                continue
            amount_raw = pick_amount(body, amts)
            amount = amount_raw if cat == 'income' else -amount_raw
            sender = _h(msg,'From') or ''
            snippet = (msg.get('snippet') or '')[:500]
            rec = dict(
                msg_id=msg['id'], ts=ts_ms//1000, ymd=ymd, sender=sender,
                subject=subj, category=cat, amount=amount, amount_raw=amount_raw,
                snippet=snippet
            )
            insert_tx(con, rec)
            cnt += 1

            body = gb._msg_text(msg)
            ymd = extract_op_date(body) or ymd
            # domyślna data z Gmaila
            ts_ms = int(msg.get('internalDate','0'))
            ymd = datetime.datetime.fromtimestamp(ts_ms/1000).strftime('%Y-%m-%d')
            # nadpisz, jeśli w treści jest Data operacji / Data waluty
            ymd = extract_op_date(body) or ymd

            body = gb._msg_text(msg)
            ymd = extract_op_date(body) or ymd
            # domyślna data z wewnętrznego znacznika Gmaila
            ts_ms = int(msg.get('internalDate','0'))
            ymd = datetime.datetime.fromtimestamp(ts_ms/1000).strftime('%Y-%m-%d')
            # jeśli w treści jest 'Data operacji'/'Data waluty', nadpisz
            ymd = extract_op_date(body) or ymd
            snippet = (msg.get('snippet') or '')[:500]
            rec = dict(
                msg_id=msg['id'], ts=ts_ms//1000, ymd=ymd, sender=sender,
                subject=subj, category=cat, amount=amount, amount_raw=amount_raw,
                snippet=snippet
            )
            insert_tx(con, rec)
            cnt+=1
        pageToken = res.get('nextPageToken')
        if not pageToken: break
    con.commit()
    print(f"@#@Załadowano rekordów: {cnt}@#@")

def _h(msg,name):
    for h in msg.get('payload',{}).get('headers',[]):
        if h.get('name','').lower()==name.lower():
            return h.get('value','')
    return ''

def report_monthly():
    con = ensure_db()
    cur = con.execute("""
      SELECT substr(ymd,1,7) AS ym,
             ROUND(SUM(CASE WHEN amount>0 THEN amount ELSE 0 END),2) AS income,
             ROUND(SUM(CASE WHEN amount<0 THEN -amount ELSE 0 END),2) AS expenses,
             ROUND(SUM(amount),2) AS net
      FROM tx
      GROUP BY ym
      ORDER BY ym;
    """)
    for ym,inc,exp,net in cur.fetchall():
        print(f"{ym}  income:{inc:.2f}  expenses:{exp:.2f}  net:{net:.2f}")

def report_fuel_monthly():
    con = ensure_db()
    cur = con.execute("""
      SELECT substr(ymd,1,7) AS ym,
             ROUND(SUM(CASE WHEN category='fuel' THEN -amount ELSE 0 END),2) AS fuel
      FROM tx GROUP BY ym ORDER BY ym;
    """)
    for ym, fuel in cur.fetchall():
        print(f"{ym}  fuel:{fuel:.2f}")

def main():
    if len(sys.argv)<2:
        print("Usage: bank_etl <ingest|mreport|fuel> [gmail_query]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd=='ingest':
        q = sys.argv[2] if len(sys.argv)>2 else 'newer_than:90d'
        ingest(q)
    elif cmd=='mreport':
        report_monthly()
    elif cmd=='fuel':
        report_fuel_monthly()
    else:
        print("Unknown command")

if __name__=='__main__':
    main()


ATT_DIR = os.path.expanduser('~/.local/share/bankdb/attachments')
os.makedirs(ATT_DIR, exist_ok=True)

def _safe_decode(b):
    for enc in ('utf-8','cp1250','iso-8859-2','latin-2'):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode('utf-8','ignore')

def _download_attachments(svc, msg, outdir=ATT_DIR):
    files = []
    os.makedirs(outdir, exist_ok=True)

    def save_part(mid, part, tag):
        fn = part.get('filename') or ''
        body = part.get('body', {}) or {}
        att_id = body.get('attachmentId')
        if fn and att_id:
            att = svc.users().messages().attachments().get(userId='me', messageId=mid, id=att_id).execute()
            data = att.get('data')
            if not data:
                return
            raw = base64.urlsafe_b64decode(data)
            safe_fn = fn.replace('/', '_')
            path = os.path.join(outdir, f"{mid}_{safe_fn}")
            with open(path, 'wb') as f:
                f.write(raw)
            files.append(path)

    def walk(mid, part, path='payload'):
        # Zapisz jeśli to realny załącznik w tej części
        save_part(mid, part, path)
        mt = (part.get('mimeType') or '').lower()
        body = part.get('body', {}) or {}

        # Specjalny przypadek: message/rfc822 (przekazana dalej wiadomość)
        if mt == 'message/rfc822' and 'parts' in part:
            for i, sub in enumerate(part.get('parts') or [], 1):
                walk(mid, sub, f"{path}.rfc822[{i}]")

        # Zwykłe zagnieżdżone części
        for i, sub in enumerate(part.get('parts') or [], 1):
            walk(mid, sub, f"{path}.parts[{i}]")

    payload = (msg.get('payload') or {})
    # czasem root payload sam ma filename/attachmentId
    walk(msg['id'], payload, 'payload')
    return files

def _iter_text_lines_from_file(path):
    name = path.lower()
    # spróbuj rozpakować ZIP i czytać pliki w środku
    if name.endswith('.zip'):
        with zipfile.ZipFile(path,'r') as z:
            for n in z.namelist():
                if n.lower().endswith(('.csv','.txt','.htm','.html')):
                    with z.open(n) as fh:
                        yield from _safe_decode(fh.read()).splitlines()
        return
    # XLSX (jeśli masz openpyxl)
    if name.endswith('.xlsx'):
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            for ws in wb.worksheets:
                for row in ws.iter_rows(values_only=True):
                    line = " | ".join("" if v is None else str(v) for v in row)
                    yield line
            return
        except Exception:
            pass
    # CSV
    if name.endswith('.csv'):
        try:
            with open(path,'rb') as f:
                txt = _safe_decode(f.read())
            # spróbuj średnik; jak nie chwyci, to przecinek
            for delim in ('; ',','):
                try:
                    reader = csv.reader(io.StringIO(txt), delimiter=delim)
                    for row in reader:
                        yield " | ".join(row)
                    return
                except Exception:
                    continue
        except Exception:
            pass
    # TXT/HTML/INNE jako tekst
    try:
        with open(path,'rb') as f:
            txt = _safe_decode(f.read())
        for line in txt.splitlines():
            yield line
    except Exception:
        return

DATE_RE = re.compile(r'(\\d{4}-\\d{2}-\\d{2})|(\\d{2}\\.\\d{2}\\.\\d{4})')
def _normalize_date(s):
    if not s: return None
    if '.' in s:
        d,m,y = s.split('.'); return f"{y}-{m}-{d}"
    return s

def _amount_from_line(line):
    amts = gb._amounts(line)
    if not amts: return None
    # preferuj dodatnie kwoty (wpływy)
    pos = [a for a in amts if a > 0]
    return pos[0] if pos else amts[0]

def process_msg_attachments(svc, msg, con, only_month_prefix=None):
    """
    Pobiera załączniki, czyta linie tekstu, szuka dat i kwot.
    only_month_prefix np. '2025-07' żeby ograniczyć import do lipca.
    """
    inserted = 0
    files = _download_attachments(svc, msg)
    if not files:
        return 0
    subj = _h(msg,'Subject') or 'Załącznik'
    sender = _h(msg,'From') or ''
    for path in files:
        for line in _iter_text_lines_from_file(path):
            m = DATE_RE.search(line)
            if not m: 
                continue
            ymd = _normalize_date(m.group(1) or m.group(2))
            if not ymd: 
                continue
            if only_month_prefix and not ymd.startswith(only_month_prefix):
                continue
            amt = _amount_from_line(line)
            if not amt or amt <= 0:
                continue
            # budujemy rekord zgodny ze schematem insert_tx
            ts = int(datetime.datetime.strptime(ymd,'%Y-%m-%d').timestamp())
            rec = dict(
                msg_id=f"att:{msg['id']}:{hash(line)%10_000_000}",
                ts=ts, ymd=ymd, sender=sender, subject=subj + " [att]",
                category='income', amount=amt, amount_raw=amt, snippet=line[:240]
            )
            insert_tx(con, rec)
            inserted += 1
    return inserted